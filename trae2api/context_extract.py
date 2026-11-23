"""Extract workspace/editor context from the *client's* message stream.

Why not a TRAE2API_WORKSPACE env var: trae2api is a proxy. Its callers are
agent clients (Claude Code, Codex, Cline, DeepSeek harness, ...) that each
carry their own working-directory knowledge in the request - they never read
our configuration. The IDE-side equivalents (VSCode workspace API, active
editor) arrive here as *message content*, so we mine that.

Recognised shapes (verified against the clients' own prompt templates):
  Claude Code  : system "Working directory: <path>" + "Primary working directory"
                 + <system-reminder> blocks, file references like
                 "Note: /abs/path was read before..."
  Codex / CLI  : "<environment>...Working directory: <path>...</environment>"
  Cline        : "<system-reminder> ... cwd ..." and
                 [edit_file for 'path'] / file_contents blocks
  Generic      : "cwd: <path>", "workspace: <path>", "project: <path>"
  File mentions: @路径 / #工作区 / 反引号路径 / "D:\\..." style absolute paths
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- client prompt markers (from the harnesses' own templates) ---------------
# NOTE: DSH (DeepSeek Harness) writes the path JSON-quoted with a trailing dot:
#   Current working directory: "D:\workspace\trae2api".
# (packages/session/working-directory/src/index.ts:173)
CWD_PATTERNS = [
    re.compile(r'Current working directory:\s*"([^"]+)"'),
    # DSH change notices: The working directory changed from "D:\old" to "D:\new".
    re.compile(r'The working directory (?:is now|changed from "[^"]*" to)\s*"([^"]+)"'),
    re.compile(r"^Working directory:\s*(.+)$", re.MULTILINE),
    re.compile(r"Primary working directory:\s*(.+)$", re.MULTILINE),
    re.compile(r"\bWorking directory:\s*(.+)$", re.MULTILINE),
    re.compile(r"\bcwd:\s*([^\n<>\"]+)", re.IGNORECASE),
    re.compile(r"\bworkspace(?: root| folder| path)?:\s*([^\n<>\"]+)", re.IGNORECASE),
]

# paths that look like filesystem roots
WIN_PATH = re.compile(r"\b([A-Za-z]:[\\/][^\s\"'<>,;)\]]{1,200})")
POSIX_PATH = re.compile(r"(?<![\w./-])(/[^\s\"'<>,;)\]]{2,200})")

# file-mention markers clients embed when attaching context
FILE_REF_MARKERS = [
    "<file path=", "file_contents", "<file_contents>", "[edit_file for",
    "was read before", "<system-reminder>", "Note: ", "cat > ",
]

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea", ".vscode"}


@dataclass
class WorkspaceContext:
    folders: list[str] = field(default_factory=list)
    active_files: list[str] = field(default_factory=list)   # currently-open/edited files
    mentioned: list[str] = field(default_factory=list)      # @/path or inline file refs
    selections: list[dict] = field(default_factory=list)    # {file_path,start_line,end_line}
    raw_markers: list[str] = field(default_factory=list)    # which harness was detected

    def folders_payload(self) -> list[dict]:
        return [{"path": p, "name": Path(p).name} for p in dict.fromkeys(self.folders)]

    def mention_context(self) -> dict:
        files = [{"file_path": p} for p in dict.fromkeys(self.active_files + self.mentioned)]
        folders = [{"path": p} for p in dict.fromkeys(self.folders)]
        return {
            "hashWorkspace": bool(folders),
            "hashFolder": bool(folders),
            "hashFiles": files,
            "hashFolders": folders,
            "hashSymbols": [],
            "hashDocs": [],
            "hashRuleFiles": [],
            "onlyMention": False,
            "hashWebs": [],
            "autoRuleCount": 0,
        }


def _norm(path: str) -> str:
    p = str(path).strip().strip("`'\"").rstrip("\\/.,;:)")
    return p


def _looks_like_path(s: str) -> bool:
    if len(s) < 2 or len(s) > 260:
        return False
    if s.startswith(("http://", "https://", "//", "/api/", "<")):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", s):  # windows drive
        return True
    if s.startswith("/") and s.count("/") >= 1 and not s.startswith(("//",)):
        # posix: require an existing root-ish prefix, else it's likely prose
        return Path(s).exists() or s.startswith(("/home/", "/Users/", "/tmp/", "/workspace", "/repo", "/app", "/data"))
    return False


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                parts.append(str(blk.get("text", "")))
            elif isinstance(blk, str):
                parts.append(blk)
        return "\n".join(parts)
    return ""


def extract_workspace(messages: list[dict]) -> WorkspaceContext:
    """Mine the request's messages for working directory / open files / mentions."""
    ctx = WorkspaceContext()
    texts: list[tuple[str, str]] = []  # (role, text)

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        text = _content_text(m.get("content"))
        if text:
            texts.append((m.get("role", "user"), text))

    all_text = "\n".join(t for _, t in texts)

    # --- 1. harness detection -------------------------------------------------
    if any(marker in all_text for marker in _CLAUDE_MARKERS):
        ctx.raw_markers.append("claude-code")
    if any(marker in all_text for marker in _CODEX_MARKERS):
        ctx.raw_markers.append("codex-cli")
    if "Current runtime context." in all_text:
        # DSH snapshot header (packages/core/system-prompt/src/index.ts:317)
        ctx.raw_markers.append("dsh")
    if "<system-reminder>" in all_text:
        ctx.raw_markers.append("cline/system-reminder")

    # --- 2. working directory (authoritative first) --------------------------
    # DSH carries the cwd inside a USER message (the runtime-context snapshot),
    # not a system prompt, so every role is scanned. The DSH pattern is quoted
    # and therefore wins over the loose unquoted ones.
    for _, text in texts:
        for pat in CWD_PATTERNS:
            for m in pat.finditer(text):
                cand = _norm(m.group(1))
                if cand and _looks_like_path(cand) and cand not in ctx.folders:
                    ctx.folders.append(cand)

    # --- 3. files the harness says are open / edited / read -------------------
    for marker in ("<file path=",):
        for m in re.finditer(re.escape(marker) + r'"?([^">\s]+)"?', all_text):
            p = _norm(m.group(1))
            if _looks_like_path(p):
                ctx.active_files.append(p)
    for m in re.finditer(r"\[edit_file for '([^']+)'\]", all_text):
        p = _norm(m.group(1))
        if _looks_like_path(p):
            ctx.active_files.append(p)
    for m in re.finditer(r"Note:\s*([^\s]+)\s+was read before", all_text):
        p = _norm(m.group(1))
        if _looks_like_path(p):
            ctx.mentioned.append(p)
    # file_contents / <file ...> blocks
    for m in re.finditer(r"<file[^>]*path=\"([^\"]+)\"", all_text):
        p = _norm(m.group(1))
        if _looks_like_path(p):
            ctx.mentioned.append(p)

    # --- 4. explicit @mentions / inline absolute paths (only if nothing yet) --
    if not ctx.folders:
        # @path / #workspace style mentions in the last user message
        user_text = "\n".join(t for r, t in texts if r == "user")
        for m in re.finditer(r"@([^\s@]+)", user_text):
            cand = _norm(m.group(1))
            if _looks_like_path(cand):
                ctx.folders.append(cand)
        # windows absolute paths mentioned in the request
        for m in WIN_PATH.finditer(user_text):
            cand = _norm(m.group(1))
            if _looks_like_path(cand) and os.path.isdir(cand):
                ctx.folders.append(cand)

    # de-dup, keep order, drop nested duplicates (keep the shallowest)
    ctx.folders = _dedupe_nested(ctx.folders)
    ctx.active_files = list(dict.fromkeys(ctx.active_files))
    ctx.mentioned = list(dict.fromkeys(ctx.mentioned))
    return ctx


def _dedupe_nested(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        if not any(p != q and (p == q or p.startswith(q.rstrip("\\/") + os.sep)) for q in paths):
            out.append(p)
    return list(dict.fromkeys(out))


_CLAUDE_MARKERS = (
    "You are an interactive agent that helps users with software engineering tasks",
    "Primary working directory",
    "<system-reminder>",
    "Filesystem sandboxing defines which files can be read or written",
)

_CODEX_MARKERS = (
    "<environment>",
    "Working directory:",
    "Codex CLI",
)
