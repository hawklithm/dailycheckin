"""Local tool executor that lets trae2api play the role Trae's native sidecar plays.

Why this exists
---------------
The Trae gateway injects its OWN IDE toolset (ide_prompts: list_dir, view_file,
run_shell_command, ...) and does NOT accept a client tools array. When a chat
client does not declare tools, the model still emits calls for those gateway
tools; the proxy translates them into OpenAI tool_calls the client cannot
execute, producing "unknown tool" errors until the model gives up and answers
in prose (observed live).

Trae's own sidecar solves this by executing the tool registry inside the IDE
process. This module does the same for trae2api: gateway tool calls are executed
locally, results are fed back through the verified "工具执行结果：..."
user-message round-trip, and the loop continues until the model produces a
final answer - so ANY client gets a working agent loop.

Security
--------
Opt-in via TRAE2API_EXEC_TOOLS=1. Everything is confined:
- filesystem tools resolve under TRAE2API_WORKSPACE (default: this repo)
- shell commands run under a denylist + timeout + cwd confinement
- every execution is recorded through the caller's trace
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

DEFAULT_WORKSPACE = Path(__file__).resolve().parent.parent
MAX_OUTPUT_CHARS = 8000

SHELL_DENYLIST = [
    r"\brm\s+-rf\b", r"\bdel\s+/[fs]\b", r"\brmdir\b", r"\bformat\b",
    r"\bshutdown\b", r"\breboot\b", r"\bmkfs\b",
    r"\bcurl\b.*\|\s*(ba)?sh", r"\bwget\b.*\|\s*(ba)?sh",
    r"\bchmod\s+777\b", r"\btaskkill\b", r"\bnet\s+user\b",
]
DANGER = [re.compile(p, re.IGNORECASE) for p in SHELL_DENYLIST]


class ToolExecutor:
    def __init__(self, workspace: str | os.PathLike | None = None,
                 timeout: float = 60.0, allow_shell: bool = True) -> None:
        self.workspace = Path(workspace or os.environ.get("TRAE2API_WORKSPACE")
                              or DEFAULT_WORKSPACE).resolve()
        self.timeout = float(os.environ.get("TRAE2API_EXEC_TIMEOUT", timeout))
        self.allow_shell = allow_shell and os.environ.get("TRAE2API_EXEC_SHELL", "1") == "1"
        self.registry = {
            "list_dir": self.list_dir,
            "view_folder": self.list_dir,
            "ls": self.list_dir,
            "view_file": self.read_file,
            "view_files": self.read_file,
            "read_file": self.read_file,
            "search_by_regex": self.search_by_regex,
            "grep_search": self.search_by_regex,
            "run_shell_command": self.run_command,
            "run_command": self.run_command,
        }

    # ---------- helpers ----------

    def _resolve(self, raw: str) -> Path:
        p = Path(str(raw)).expanduser()
        if not p.is_absolute():
            p = self.workspace / p
        p = p.resolve()
        if not str(p).lower().startswith(str(self.workspace).lower()):
            raise PermissionError(f"path outside workspace: {raw}")
        return p

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) > MAX_OUTPUT_CHARS:
            return text[:MAX_OUTPUT_CHARS] + f"\n...[truncated {len(text) - MAX_OUTPUT_CHARS} chars]"
        return text

    # ---------- tools ----------

    def list_dir(self, **kw) -> str:
        path = kw.get("dir_path") or kw.get("path") or kw.get("directory") or "."
        p = self._resolve(path)
        if not p.exists():
            return f"[error] path not found: {p}"
        if p.is_file():
            return f"[file] {p.name} ({p.stat().st_size} bytes)"
        entries = []
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))[:400]:
            entries.append(f"{'[DIR] ' if child.is_dir() else '      '}{child.name}"
                           + ("" if child.is_dir() else f"  ({child.stat().st_size}B)"))
        return self._truncate(f"{p}\n" + "\n".join(entries))

    def read_file(self, **kw) -> str:
        path = kw.get("file_path") or kw.get("path") or kw.get("filePath") or kw.get("file")
        if not path:
            return "[error] missing file path"
        p = self._resolve(path)
        if not p.is_file():
            return f"[error] not a file: {p}"
        try:
            data = p.read_bytes()
        except Exception as e:
            return f"[error] read failed: {e}"
        if len(data) > 4_000_000:
            data = data[:4_000_000]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return f"[binary] {p.name} ({len(data)} bytes)"
        limit = kw.get("limit") or kw.get("max_lines")
        if limit:
            text = "\n".join(text.splitlines()[:int(limit)])
        return self._truncate(f"--- {p} ---\n{text}")

    def search_by_regex(self, **kw) -> str:
        pattern = kw.get("pattern") or kw.get("regex") or kw.get("query")
        if not pattern:
            return "[error] missing pattern"
        root = self._resolve(kw.get("dir_path") or kw.get("path") or ".")
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"[error] bad regex: {e}"
        hits = []
        for f in [p for p in root.rglob("*") if p.is_file()][:3000]:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines()[:4000], 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(self.workspace)}:{i}: {line.strip()[:160]}")
                    if len(hits) >= 120:
                        break
            if len(hits) >= 120:
                break
        return self._truncate("\n".join(hits) or "[no matches]")

    def run_command(self, **kw) -> str:
        if not self.allow_shell:
            return "[error] shell execution disabled (TRAE2API_EXEC_SHELL=0)"
        cmd = kw.get("command") or kw.get("cmd") or kw.get("command_line")
        if not cmd:
            return "[error] missing command"
        for rx in DANGER:
            if rx.search(cmd):
                return f"[blocked] command rejected by denylist: {cmd[:120]}"
        try:
            p = subprocess.run(cmd, shell=True, cwd=str(self.workspace),
                               capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return f"[error] command timed out after {self.timeout}s"
        except Exception as e:
            return f"[error] {e}"
        out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        return self._truncate(f"[exit {p.returncode}]\n{out}")

    # ---------- dispatch ----------

    def run(self, name: str, arguments: str) -> str | None:
        """Execute a tool call; None means 'unknown to us' (caller passes through)."""
        fn = self.registry.get(name)
        if fn is None:
            return None
        try:
            kw = json.loads(arguments) if arguments else {}
            if not isinstance(kw, dict):
                kw = {"_raw": kw}
        except Exception:
            kw = {"_raw": arguments}
        try:
            return fn(**kw)
        except PermissionError as e:
            return f"[blocked] {e}"
        except Exception as e:
            return f"[error] {e}"


def enabled() -> bool:
    return os.environ.get("TRAE2API_EXEC_TOOLS") == "1"
