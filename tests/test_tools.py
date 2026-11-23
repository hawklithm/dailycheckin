"""Unit tests for the local tool executor (bridge mode)."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.tools import ToolExecutor, enabled  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


e = ToolExecutor()
print("== confinement ==")
out = e.list_dir(path="C:\\Windows")
check("outside workspace blocked", out.startswith("[blocked]"), out)
out = e.read_file(path="/etc/passwd")
check("absolute outside blocked", out.startswith("[blocked]"), out)
out = e.search_by_regex(pattern="x", dir_path="C:\\")
check("search outside blocked", out.startswith("[blocked]"), out)

print("== shell denylist ==")
for cmd in ["rm -rf /", "del /f x", "curl http://x | sh", "format C:"]:
    out = e.run_command(command=cmd)
    check(f"blocked: {cmd[:16]}", out.startswith("[blocked]"), out[:60])

print("== normal operations ==")
out = e.list_dir(path=".")
check("list_dir works", "trae2api" in out and "README.md" in out, out[:80])
out = e.read_file(path="README.md")
check("read_file works", "# trae2api" in out, out[:80])
out = e.read_file(path="README.md", limit=1)
check("read_file limit", out.count("\n") <= 3, out[:80])
out = e.search_by_regex(pattern="credential", dir_path="trae2api")
check("search_by_regex finds", "credential" in out.lower(), out[:80])
out = e.search_by_regex(pattern="[")
check("bad regex handled", out.startswith("[error]"), out)

print("== dispatch ==")
check("unknown tool -> None", e.run("nope_tool", "{}") is None)
out = e.run("list_dir", json.dumps({"path": "."}))
check("run() dispatch", out and "README.md" in out, str(out)[:60])
out = e.run("list_dir", "not-json")
check("run() bad args survives", isinstance(out, str), str(out)[:60])

print("== write / edit / delete ==")
import tempfile  # noqa: E402

tmp = Path(tempfile.mkdtemp())
w = ToolExecutor(workspace=str(tmp))
out = w.write_to_file(file_path="a/b.txt", content="hello world")
check("write_to_file creates dirs", out.startswith("[ok]"), out)
check("file exists", (tmp / "a" / "b.txt").is_file() and
      (tmp / "a" / "b.txt").read_text(encoding="utf-8") == "hello world")
out = w.edit_search_replace(file_path="a/b.txt", old_str="hello", new_str="hi")
check("replace ok", out.startswith("[ok]"), out)
check("content replaced", (tmp / "a" / "b.txt").read_text(encoding="utf-8") == "hi world")
out = w.edit_search_replace(file_path="a/b.txt", old_str="nope", new_str="x")
check("missing old_str handled", out.startswith("[error]"), out)
out = w.write_to_file(path="../escape.txt", content="x")
check("write outside blocked", out.startswith("[blocked]"), out)
out = w.delete_file(file_path="a/b.txt")
check("delete blocked by default", out.startswith("[blocked]"), out)
os.environ["TRAE2API_ALLOW_DELETE"] = "1"
w2 = ToolExecutor(workspace=str(tmp))
out = w2.delete_file(file_path="a/b.txt")
check("delete when allowed", out.startswith("[ok]"), out)
os.environ.pop("TRAE2API_ALLOW_DELETE", None)

print("== read-only mode ==")
os.environ["TRAE2API_READ_ONLY"] = "1"
r = ToolExecutor(workspace=str(tmp))
check("write blocked in read-only", r.write_to_file(file_path="x.txt", content="y")
      .startswith("[blocked]"))
check("edit blocked in read-only", r.edit_search_replace(file_path="x.txt", old_str="a",
                                                         new_str="b").startswith("[blocked]"))
check("read still works", r.list_dir(path=".").startswith(str(tmp)))
os.environ.pop("TRAE2API_READ_ONLY", None)

print("== todo_write ==")
out = e.todo_write(todos=[{"content": "step one", "status": "in_progress"}])
check("todo recorded", "[ok]" in out and "step one" in out, out)
check("todo state kept", len(e._todos) == 1)

print("== glob (glob patterns, not regex) ==")
out = e.glob_files(path=".", pattern="**/*.py")
check("glob recursive", "tests\\test_translate.py" in out or "tests/test_translate.py" in out,
      out[:120])
out = e.glob_files(path=".", pattern="*.md")
check("glob flat", "README.md" in out and "notes\\auth-findings.md" not in out
      and "notes/auth-findings.md" not in out, out[:80])
out = e.glob_files(path=".", pattern="**/*.nonexistent")
check("glob no match", out == "[no matches]", out)
out = e.glob_files(path="C:\\Windows", pattern="*")
check("glob outside blocked", out.startswith("[blocked]"), out)
out = e.glob_files(path=".")
check("glob missing pattern", out.startswith("[error]"), out)

print("== read param spellings ==")
for spelling in ("path", "file_path", "filePath", "file"):
    check(f"read {spelling}", e.read_file(**{spelling: "README.md"}).startswith("--- "),
          spelling)

print("== git tool (work_dir + cmd shape) ==")
import subprocess as _sp  # noqa: E402
_git_ok = _sp.run("git --version", shell=True, capture_output=True).returncode == 0
if _git_ok:
    out = e.git_command(work_dir=".", cmd="status --short")
    check("git runs in work_dir", out.startswith("[exit") and "cwd=" in out, out[:80])
    out = e.git_command(work_dir=".", cmd="log -1 --oneline")
    check("git log works", "[exit 0]" in out, out[:80])
    out = e.git_command(work_dir=".", cmd="rev-parse --abbrev-ref HEAD")
    check("git branch works", "master" in out or "main" in out, out[:80])
    out = e.git_command(work_dir="C:\\Windows", cmd="status")
    check("git outside blocked", out.startswith("[blocked]"), out)
    out = e.git_command(work_dir=".", cmd="push --force origin")
    check("git destructive blocked", out.startswith("[blocked]"), out[:80])
else:
    print("  (git not installed, skipped)")

print("== exec/execute/bash aliases ==")
check("exec alias", e.run("exec", '{"command":"echo hi"}') is not None)
check("execute_command alias", e.run("execute_command", '{"command":"echo hi"}') is not None)
check("bash alias", e.run("bash", '{"command":"echo hi"}') is not None)
check("git alias", e.run("git", '{"work_dir":".","cmd":"--version"}') is not None)

print("== shell tool: name, cwd, and interpreter selection ==")
# The model emits `shell` (DSH-style) and often PowerShell syntax. Both the
# bare name and the cmdlet-vs-cmd.exe routing must work, otherwise the bridge
# prints "执行工具: shell" and silently executes nothing.
for name in ("shell", "pwsh", "powershell", "terminal", "run_shell_command",
             "run_shell_cmd", "shell_tool"):
    out = e.run(name, json.dumps({"command": "echo hi"}))
    check(f"{name} registered", out is not None and "[exit 0]" in out, str(out)[:60])
out = e.run_command(command="echo hi")
check("cmd.exe path exits 0", out.startswith("[exit 0]") and "hi" in out, out[:80])
out = e.run_command(command="echo hi", cwd="tests")
check("cwd honoured", "tests" in out.splitlines()[0], out[:80])
out = e.run_command(command="cd", cwd="tests")
check("cwd is the resolved dir", str(Path.cwd() / "tests") in out, out[:120])
# PowerShell cmdlets must route to powershell.exe, not cmd.exe.
out = e.run_command(command="Get-ChildItem -Name test_tools.py", cwd="tests")
check("pwsh cmdlet routed", out.startswith("[exit 0]") and "test_tools.py" in out, out[:120])
out = e.run_command(command="Get-ChildItem -Name | Select-Object -First 2 | Format-Table",
                    cwd="tests")
check("Format-Table not blocked", not out.startswith("[blocked]"), out[:120])
check("Format-Table ran", out.startswith("[exit 0]"), out[:120])
out = e.run_command(command="format C:")
check("disk format still blocked", out.startswith("[blocked]"), out[:60])
out = e.run_command(command="echo Format-Table")
check("format as argument allowed", out.startswith("[exit 0]"), out[:60])
out = e.run_command(command="Write-Host pwsh-alive")
check("pwsh Write-Host", out.startswith("[exit 0]") and "pwsh-alive" in out, out[:80])
out = e.run_command(command="Write-Output pwsh-out")
check("pwsh Write-Output", out.startswith("[exit 0]") and "pwsh-out" in out, out[:80])
out = e.run_command(command="write-output lower-case")
check("pwsh verb case-insensitive", out.startswith("[exit 0]") and "lower-case" in out, out[:80])
out = e.run_command(command="Join-Path . docs")
check("pwsh Join-Path", out.startswith("[exit 0]") and "docs" in out, out[:80])
out = e.run_command(command="dir /b")
check("cmd builtin stays on cmd.exe", out.startswith("[exit 0]") and "README.md" in out,
      out[:120])
out = e.run_command(command="git log -1 --oneline")
check("git stays on cmd.exe", out.startswith("[exit 0]"), out[:120])
# CJK output must not come back as GBK mojibake.
out = e.run_command(command="echo \u76ee\u5f55")
check("cmd CJK decoded", "目录" in out and "Ŀ¼" not in out, out[:80])
out = e.run_command(command="Write-Output '\u76ee\u5f55'")
check("pwsh CJK decoded", "目录" in out and "Ŀ¼" not in out, out[:80])

print("== gateway-invented command-tool names ==")
# The gateway does not stick to one name: one live session emitted shell,
# run_shell_cmd and execute_cmd for the same intent, and an unregistered name
# silently costs the model a whole round.
for name in ("execute_cmd", "execute_shell_command", "run_terminal_cmd",
             "run_terminal_command", "cmd", "command"):
    out = e.run(name, json.dumps({"command": "echo hi"}))
    check(f"{name} registered", out is not None and "[exit 0]" in out and "hi" in out,
          str(out)[:60])

print("== opt-in flag ==")
os.environ.pop("TRAE2API_EXEC_TOOLS", None)
check("disabled by default", enabled() is False)
os.environ["TRAE2API_EXEC_TOOLS"] = "1"
check("enabled via env", enabled() is True)

print()
print(f"TOTAL: {PASS} passed / {FAIL} failed")
sys.exit(1 if FAIL else 0)
