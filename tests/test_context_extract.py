"""Unit tests: workspace context extraction from real client message shapes."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.context_extract import extract_workspace  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


print("== Claude Code shape (system + system-reminder) ==")
msgs = [
    {"role": "system", "content": (
        "You are an interactive agent that helps users with software engineering tasks. "
        "# Environment\nWorking directory: D:\\workspace\\trae2api\n"
        "Primary working directory: D:\\workspace\\trae2api\n"
        "Filesystem sandboxing defines which files can be read or written.")},
    {"role": "user", "content": (
        "<system-reminder>\nAs you answer the user's questions, you can use the following context:\n"
        "# currentDate\n  2026-10-25\n</system-reminder>\n\n帮我把 trae2api/tools.py 里的 run_command 加上超时参数")},
]
ctx = extract_workspace(msgs)
check("claude harness detected", "claude-code" in ctx.raw_markers, ctx.raw_markers)
check("working dir found", "D:\\workspace\\trae2api" in ctx.folders, ctx.folders)

print("== Claude Code with read file note ==")
msgs = [
    {"role": "system", "content": "Working directory: /home/user/project"},
    {"role": "user", "content": "Note: /home/user/project/src/main.py was read before the last conversation was summarized.\n现在改一下 main 函数"},
]
ctx = extract_workspace(msgs)
check("posix cwd found", "/home/user/project" in ctx.folders, ctx.folders)
check("read file tracked", "/home/user/project/src/main.py" in ctx.mentioned, ctx.mentioned)

print("== Codex CLI shape ==")
msgs = [
    {"role": "user", "content": (
        "<environment>\n<workspace_root>/workspace/repo</workspace_root>\n"
        "Working directory: /workspace/repo\n</environment>\n\nfix the failing test")},
]
ctx = extract_workspace(msgs)
check("codex harness detected", "codex-cli" in ctx.raw_markers, ctx.raw_markers)
check("codex cwd found", "/workspace/repo" in ctx.folders, ctx.folders)

print("== Cline edit_file shape ==")
msgs = [
    {"role": "user", "content": (
        "<system-reminder>cwd: D:\\repos\\web</system-reminder>\n"
        "[edit_file for 'D:\\repos\\web\\src\\app.js'] Result: success")},
]
ctx = extract_workspace(msgs)
check("cline cwd found", "D:\\repos\\web" in ctx.folders, ctx.folders)
check("edited file tracked", "D:\\repos\\web\\src\\app.js" in ctx.active_files, ctx.active_files)

print("== plain chat with inline paths ==")
msgs = [
    {"role": "user", "content": "请对比 D:\\workspace\\trae2api 和 D:\\workspace\\workbuddy2api 的目录结构"},
]
ctx = extract_workspace(msgs)
check("existing dirs become folders",
      "D:\\workspace\\trae2api" in ctx.folders and "D:\\workspace\\workbuddy2api" in ctx.folders,
      ctx.folders)

print("== DeepSeek Harness shape (quoted cwd inside a USER snapshot) ==")
msgs = [
    {"role": "user", "content": (
        "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n"
        "Current DSH file policy: danger-full-access. The DSH file sandbox does not restrict "
        "file modifications by available operations.\n\n"
        "Current DeepSeek Harness implementation checkout: \"F:\\deepseek-harness\".\n"
        "Current working directory: \"D:\\workspace\\trae2api\".\n"
        "Current DeepSeek Harness Web GUI URL: http://127.0.0.1:3080.")},
    {"role": "user", "content": "看一下 trae2api 目录下有哪些文件"},
]
ctx = extract_workspace(msgs)
check("dsh harness detected", "dsh" in ctx.raw_markers, ctx.raw_markers)
check("dsh quoted cwd found", "D:\\workspace\\trae2api" in ctx.folders, ctx.folders)
check("checkout path not mistaken for cwd",
      "F:\\deepseek-harness" not in ctx.folders, ctx.folders)

print("== DSH cleared snapshot ==")
ctx = extract_workspace([
    {"role": "user", "content": "Current runtime context: none. Earlier runtime-context snapshots no longer apply."},
])
check("cleared snapshot -> no folders", ctx.folders == [], ctx.folders)

print("== DSH working-directory change notice ==")
ctx = extract_workspace([
    {"role": "user", "content": 'The working directory changed from "D:\\old" to "D:\\new".'},
    {"role": "user", "content": "继续"},
])
check("change notice parsed", "D:\\new" in ctx.folders, ctx.folders)

print("== no context at all ==")
ctx = extract_workspace([{"role": "user", "content": "hello there"}])
check("no folders", ctx.folders == [])
check("no markers", ctx.raw_markers == [])

print("== payload shapes ==")
ctx = extract_workspace([
    {"role": "system", "content": "Working directory: D:\\workspace\\trae2api"},
    {"role": "user", "content": "<file path=\"D:\\workspace\\trae2api\\README.md\">内容</file>\n改一下 README"},
])
fp = ctx.folders_payload()
check("folders_payload shape", fp and set(fp[0]) == {"path", "name"}, fp)
mc = ctx.mention_context()
check("mention_context keys", {"hashWorkspace", "hashFiles", "hashFolders"} <= set(mc), list(mc))
check("mention_context files", any(f["file_path"].endswith("README.md") for f in mc["hashFiles"]), mc["hashFiles"])
json.dumps({"folders": fp, "mention_context": mc}, ensure_ascii=False)
check("payloads json-serializable", True)

print("== executor rooting follows the client workspace ==")
# Regression: extra_roots alone left the executor's PRIMARY workspace at the
# proxy install dir, so `Get-ChildItem -Path .` listed trae2api instead of the
# caller's project. The client-reported folder must become the primary root.
from trae2api.server import _executor_for  # noqa: E402

_dsh = [{"role": "user", "content": (
    'Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n'
    'Current working directory: "D:\\workspace\\re_music".\n'
    "Current DSH file policy: danger-full-access.")}]
_ex, _ctx = _executor_for(_dsh)
check("primary root is client cwd", str(_ex.workspace).lower() == "d:\\workspace\\re_music",
      str(_ex.workspace))
check("client cwd is first root", str(_ex.roots[0]).lower() == "d:\\workspace\\re_music",
      _ex.roots)
check("proxy repo kept as extra root",
      any(str(r).lower().endswith("trae2api") for r in _ex.roots[1:]), _ex.roots)
_ex2, _ = _executor_for([{"role": "user", "content": "hello"}])
check("no context -> proxy repo root", str(_ex2.workspace).lower().endswith("trae2api"),
      str(_ex2.workspace))

print()
print(f"TOTAL: {PASS} passed / {FAIL} failed")
sys.exit(1 if FAIL else 0)
