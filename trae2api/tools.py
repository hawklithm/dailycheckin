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
    r"\brm\s+-rf\b", r"\bdel\s+/[fs]\b", r"\brmdir\b",
    # 'format C:' (disk format) must not match PowerShell's Format-Table /
    # Format-List cmdlets, so require a drive letter or no argument after it.
    r"\bformat\s+[A-Za-z]:", r"\bformat\s*$",
    r"\bshutdown\b", r"\breboot\b", r"\bmkfs\b",
    r"\bcurl\b.*\|\s*(ba)?sh", r"\bwget\b.*\|\s*(ba)?sh",
    r"\bchmod\s+777\b", r"\btaskkill\b", r"\bnet\s+user\b",
    # destructive git operations: a wrong commit/reset/force-push from a model
    # is unrecoverable, so block them rather than relying on git's own guards.
    r"\bgit\s+push\b.*(--force\b|-f\b|\s-f\b)",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*[dxf]",
    r"\bgit\s+checkout\s+--\s",
    r"\bgit\s+restore\s+\S+\s*$",
    r"\bgit\s+filter-branch\b",
    r"\bgit\s+rebase\b",
]
DANGER = [re.compile(p, re.IGNORECASE) for p in SHELL_DENYLIST]

# Forced on PowerShell children so their stdout is UTF-8 instead of the console
# codepage (GBK here). Without it Chinese paths come back as mojibake and the
# model cannot re-use them.
PWSH_UTF8_PREAMBLE = "$OutputEncoding=[Console]::OutputEncoding=[Text.Encoding]::UTF8;"

# PowerShell's approved verb list. A `verb-noun` token is only treated as a
# cmdlet when its verb is in this set, so `well-known` or `git-clone` stay on
# cmd.exe while `get-childitem`, `Write-Output` and `format-table` route to
# PowerShell regardless of how the model capitalised them.
PWSH_VERBS = frozenset("""
add clear close copy enter exit find format get hide join lock move new open pop
push remove rename reset resize resolve search select set show skip split start
step stop submit switch tee test trace unblock undo unlock use wait watch where
write out read invoke measure sort group compare convert import export merge
update install uninstall save restore backup check build publish register
""".split())
PWSH_CMDLET = re.compile(r"\b([A-Za-z]+)-([A-Za-z]+)\b")


def decode_output(raw: bytes | None) -> str:
    """Decode child-process output, preferring UTF-8 but tolerating GBK.

    Windows tools (cmd.exe builtins, native exes) still write in the console
    codepage, so a strict UTF-8 decode mangles them. Order matters: UTF-8 first
    because we force it for PowerShell, then the locale codepage as fallback.
    """
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


class ToolExecutor:
    def __init__(self, workspace: str | os.PathLike | None = None,
                 timeout: float = 60.0, allow_shell: bool = True,
                 extra_roots: list[str] | None = None) -> None:
        self.workspace = Path(workspace or os.environ.get("TRAE2API_WORKSPACE")
                              or DEFAULT_WORKSPACE).resolve()
        # Additional roots the executor may touch. The bridge passes the
        # workspace the CLIENT reported (its own cwd), so file tools operate
        # on the caller's project instead of the proxy's install directory.
        roots = [self.workspace]
        for r in extra_roots or []:
            try:
                rp = Path(r).expanduser().resolve()
            except Exception:
                continue
            if rp not in roots:
                roots.append(rp)
        self.roots = roots
        self.timeout = float(os.environ.get("TRAE2API_EXEC_TIMEOUT", timeout))
        self.allow_shell = allow_shell and os.environ.get("TRAE2API_EXEC_SHELL", "1") == "1"
        # write/delete are gated separately from read-only tools
        self.read_only = os.environ.get("TRAE2API_READ_ONLY") == "1"
        self.allow_delete = (not self.read_only) and os.environ.get("TRAE2API_ALLOW_DELETE") == "1"
        self._todos: list[dict] = []
        self.registry = {
            # --- read ---
            "list_dir": self.list_dir,
            "view_folder": self.list_dir,
            "ls": self.list_dir,
            "view_file": self.read_file,
            "view_files": self.read_file,
            "read_file": self.read_file,
            "read": self.read_file,
            "cat": self.read_file,
            "head": self.read_file,
            # --- search ---
            "search_by_regex": self.search_by_regex,
            "grep": self.search_by_regex,
            "search_codebase": self.search_by_regex,
            "glob": self.glob_files,
            "file_search": self.glob_files,
            "find_files": self.glob_files,
            # --- shell ---
            "run_shell_command": self.run_command,
            "run_shell_cmd": self.run_command,
            "run_command": self.run_command,
            "shell_tool": self.run_command,
            "shell": self.run_command,
            "exec": self.run_command,
            "execute_command": self.run_command,
            "execute": self.run_command,
            "bash": self.run_command,
            "terminal": self.run_command,
            "pwsh": self.run_command,
            "powershell": self.run_command,
            "git": self.git_command,
            # --- write / edit ---
            "write_to_file": self.write_to_file,
            "write_file": self.write_to_file,
            "create_file": self.write_to_file,
            "write": self.write_to_file,
            "edit_file_search_replace": self.edit_search_replace,
            "edit_file_update": self.edit_search_replace,
            "multi_edit": self.edit_search_replace,
            "edit": self.edit_search_replace,
            "str_replace_editor": self.edit_search_replace,
            "delete_file": self.delete_file,
            "todo_write": self.todo_write,
        }
        # normalised index: 'listdir'/'List_Dir' -> same key
        self._alias_index: dict[str, Any] = {}
        for key in self.registry:
            self._alias_index.setdefault(_normalise_name(key), self.registry[key])
        # short forms the model tends to invent for the edit family
        for short, target in {
            "editfile": "edit_file_search_replace",
            "edit": "edit_file_search_replace",
            "replace": "edit_file_search_replace",
            "searchreplace": "edit_file_search_replace",
            "editfileupdates": "edit_file_update",
            "editfileupdatefc": "edit_file_update",
            "editfilefastapply": "edit_file_fast_apply",
        }.items():
            if target in self.registry:
                self._alias_index.setdefault(short, self.registry[target])

    # ---------- helpers ----------

    def _resolve(self, raw: str) -> Path:
        p = Path(str(raw)).expanduser()
        if not p.is_absolute():
            p = self.workspace / p
        p = p.resolve()
        if not self._allowed(p):
            raise PermissionError(f"path outside allowed roots: {raw}")
        return p

    def _allowed(self, p: Path) -> bool:
        for root in self.roots:
            if str(p).lower() == str(root).lower():
                return True
            if str(p).lower().startswith(str(root).lower().rstrip("\\/") + os.sep):
                return True
        return False

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) > MAX_OUTPUT_CHARS:
            return text[:MAX_OUTPUT_CHARS] + f"\n...[truncated {len(text) - MAX_OUTPUT_CHARS} chars]"
        return text

    # ---------- tools ----------

    def list_dir(self, **kw) -> str:
        path = kw.get("dir_path") or kw.get("path") or kw.get("directory") or "."
        try:
            p = self._resolve(path)
        except PermissionError as e:
            return f"[blocked] {e}"
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
        try:
            p = self._resolve(path)
        except PermissionError as e:
            return f"[blocked] {e}"
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

    def glob_files(self, **kw) -> str:
        """Glob-style file search (`**/*.kt`, `*.md`). Not a regex."""
        pattern = kw.get("pattern") or kw.get("glob") or kw.get("query")
        if not pattern:
            return "[error] missing pattern"
        root_raw = kw.get("dir_path") or kw.get("path") or "."
        try:
            root = self._resolve(root_raw)
        except PermissionError as e:
            return f"[blocked] {e}"
        if not root.exists():
            return f"[error] path not found: {root}"
        try:
            import fnmatch
            pat = str(pattern).replace("\\", "/").lstrip("/")
            # Neither fnmatch nor PurePath.match anchors an un-prefixed pattern
            # ('*' crosses '/'), so match component-by-component ourselves:
            #   '*.md'        -> exactly one component, root level only
            #   'tests/*.py'  -> two components
            #   '**/*.py'     -> '**' absorbs any number of components
            pat_parts = [p for p in pat.split("/") if p]
            hits = []
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                rel_parts = [x for x in p.relative_to(root).as_posix().split("/") if x]
                if _glob_match(rel_parts, pat_parts):
                    hits.append(str(p))
                    if len(hits) >= 200:
                        break
        except Exception as e:
            return f"[error] glob failed: {e}"
        return self._truncate("\n".join(hits) or "[no matches]")

    def search_by_regex(self, **kw) -> str:
        pattern = kw.get("pattern") or kw.get("regex") or kw.get("query")
        if not pattern:
            return "[error] missing pattern"
        root_raw = kw.get("dir_path") or kw.get("path") or "."
        try:
            root = self._resolve(root_raw)
        except PermissionError as e:
            return f"[blocked] {e}"
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
        # The caller's cwd (Trae sends {command, cwd}); defaults to the primary
        # workspace so relative paths resolve there.
        work = kw.get("cwd") or kw.get("work_dir") or kw.get("path") or kw.get("dir_path")
        cwd = str(self.workspace)
        if work:
            try:
                cwd = str(self._resolve(work))
            except PermissionError as e:
                return f"[blocked] {e}"
        # The model often emits PowerShell syntax (Get-ChildItem, | Format-Table,
        # Select-Object). cmd.exe cannot run those, so pick the interpreter by
        # content. Matching the Verb-Noun convention against PowerShell's verb
        # list beats enumerating cmdlets: an enumeration silently sent
        # Write-Output / Add-Content / Join-Path to cmd.exe.
        use_pwsh = bool(
            any(m.group(1).lower() in PWSH_VERBS for m in PWSH_CMDLET.finditer(cmd))
            or re.search(r"\$env:|\$PSScriptRoot|\$_\b|^\s*&?\s*(pwsh|powershell)\b", cmd)
        )
        argv = cmd
        if use_pwsh:
            exe = "powershell.exe" if os.name == "nt" else "pwsh"
            argv = [exe, "-NoProfile", "-NonInteractive", "-Command",
                    PWSH_UTF8_PREAMBLE + cmd]
        try:
            p = subprocess.run(argv, shell=not use_pwsh, cwd=cwd,
                               capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return f"[error] command timed out after {self.timeout}s"
        except Exception as e:
            return f"[error] {e}"
        out = decode_output(p.stdout) + decode_output(p.stderr)
        return self._truncate(f"[exit {p.returncode}] (cwd={cwd})\n{out}")

    def git_command(self, **kw) -> str:
        """Dedicated git tool: the model sends {work_dir, cmd} or {path, command}.

        Runs `git <cmd>` inside work_dir (defaults to the primary workspace)
        so relative paths in the command resolve correctly.
        """
        if not self.allow_shell:
            return "[error] shell execution disabled (TRAE2API_EXEC_SHELL=0)"
        cmd = kw.get("cmd") or kw.get("command") or kw.get("command_line") or kw.get("args")
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        if not cmd:
            return "[error] missing git command"
        work = kw.get("work_dir") or kw.get("cwd") or kw.get("path") or kw.get("dir_path")
        cwd = str(self.workspace)
        if work:
            try:
                cwd = str(self._resolve(work))
            except PermissionError as e:
                return f"[blocked] {e}"
        full = f"git {str(cmd).strip()}"
        for rx in DANGER:
            if rx.search(full):
                return f"[blocked] command rejected by denylist: {full[:120]}"
        try:
            p = subprocess.run(full, shell=True, cwd=cwd,
                               capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return f"[error] git timed out after {self.timeout}s"
        except Exception as e:
            return f"[error] {e}"
        out = decode_output(p.stdout) + decode_output(p.stderr)
        return self._truncate(f"[exit {p.returncode}] (cwd={cwd})\n{out}")

    # ---------- write / edit / delete ----------

    def write_to_file(self, **kw) -> str:
        if self.read_only:
            return "[blocked] write disabled (TRAE2API_READ_ONLY=1)"
        path = kw.get("file_path") or kw.get("path") or kw.get("target_file")
        content = kw.get("content", kw.get("new_content", kw.get("new_str")))
        if not path:
            return "[error] missing file path"
        if content is None:
            return "[error] missing content"
        try:
            p = self._resolve(path)
        except PermissionError as e:
            return f"[blocked] {e}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(content), encoding="utf-8")
        except Exception as e:
            return f"[error] write failed: {e}"
        return f"[ok] wrote {p} ({len(str(content))} chars)"

    def edit_search_replace(self, **kw) -> str:
        if self.read_only:
            return "[blocked] edit disabled (TRAE2API_READ_ONLY=1)"
        path = kw.get("file_path") or kw.get("path") or kw.get("target_file")
        old = kw.get("old_str", kw.get("old_string"))
        new = kw.get("new_str", kw.get("new_string", kw.get("new_content")))
        if not path or old is None or new is None:
            return "[error] need file_path, old_str and new_str"
        try:
            p = self._resolve(path)
        except PermissionError as e:
            return f"[blocked] {e}"
        if not p.is_file():
            return f"[error] not a file: {p}"
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            return f"[error] read failed: {e}"
        count = text.count(old)
        if count == 0:
            return f"[error] old_str not found in {p}"
        if count > 1:
            return f"[error] old_str occurs {count} times; must be unique"
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        return f"[ok] replaced 1 occurrence in {p}"

    def delete_file(self, **kw) -> str:
        if not self.allow_delete:
            return "[blocked] delete disabled (set TRAE2API_ALLOW_DELETE=1 to allow)"
        path = kw.get("file_path") or kw.get("path") or kw.get("target_file")
        if not path:
            return "[error] missing file path"
        try:
            p = self._resolve(path)
        except PermissionError as e:
            return f"[blocked] {e}"
        if not p.exists():
            return f"[error] not found: {p}"
        try:
            p.unlink()
        except Exception as e:
            return f"[error] delete failed: {e}"
        return f"[ok] deleted {p}"

    def todo_write(self, **kw) -> str:
        """Plan tracking lives in the proxy; we keep it in memory and echo it."""
        items = kw.get("todos") or kw.get("items") or []
        if isinstance(items, str):
            items = [{"content": items}]
        if isinstance(items, dict):
            items = [items]
        self._todos = [i for i in items if isinstance(i, dict)]
        if not self._todos:
            return "[ok] todo list cleared"
        lines = []
        for i, t in enumerate(self._todos, 1):
            status = str(t.get("status", "pending"))
            lines.append(f"{i}. [{status}] {t.get('content', '')}")
        return "[ok] todo list:\n" + "\n".join(lines)

    # ---------- dispatch ----------

    def run(self, name: str, arguments: str) -> str | None:
        """Execute a tool call; None means 'unknown to us' (caller passes through).

        Names are looked up verbatim first, then normalised (lowercased, with
        separators removed) so model-invented variants like `listdir`,
        `ListDir` or `read file` still resolve to the registered handler.
        """
        fn = self.registry.get(name)
        if fn is None:
            fn = self._alias_index.get(_normalise_name(name))
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


def _normalise_name(name: str) -> str:
    """`listdir` / `ListDir` / `list-dir` -> `listdir` (compare key)."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _glob_match(rel_parts: list[str], pat_parts: list[str]) -> bool:
    """Component-wise glob match where '**' absorbs any number of components.

    Unlike fnmatch/PurePath.match, an un-prefixed pattern stays anchored:
    '*.md' matches only root-level .md files, 'tests/*.py' only that folder.
    """
    import fnmatch

    def rec(i: int, j: int) -> bool:
        if i == len(rel_parts):
            return j == len(pat_parts)
        if j == len(pat_parts):
            return False
        if pat_parts[j] == "**":
            # '**' absorbs zero or more components
            return rec(i, j + 1) or rec(i + 1, j)
        return fnmatch.fnmatch(rel_parts[i], pat_parts[j]) and rec(i + 1, j + 1)

    return rec(0, 0)
