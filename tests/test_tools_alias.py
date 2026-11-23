"""Unit tests: tool-name normalisation and client-workspace roots."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.tools import ToolExecutor  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


print("== name normalisation (model-invented variants) ==")
e = ToolExecutor()
for variant, expect in [
    ("listdir", "list_dir"),
    ("ListDir", "list_dir"),
    ("list-dir", "list_dir"),
    ("readfile", "read_file"),
    ("ReadFile", "read_file"),
    ("writefile", "write_to_file"),
    ("editfile", "edit_file_search_replace"),
    ("runshellcommand", "run_command"),
    ("searchbyregex", "search_by_regex"),
    ("todowrite", "todo_write"),
]:
    fn = e._alias_index.get(__import__("re").sub(r"[^a-z0-9]", "", variant.lower()))
    check(f"{variant} -> {expect}", fn is not None and fn == e.registry.get(expect),
          f"got {fn}")

print("== run() resolves variants ==")
out = e.run("listdir", '{"path": "."}')
check("run('listdir') works", out is not None and "README.md" in out, str(out)[:60])
out = e.run("ListDir", '{"path": "."}')
check("run('ListDir') works", out is not None and "README.md" in str(out), str(out)[:60])

print("== extra roots follow the client cwd ==")
tmp = Path(tempfile.mkdtemp())
(tmp / "hello.txt").write_text("from client workspace", encoding="utf-8")
other = Path(tempfile.mkdtemp())
(other / "secret.txt").write_text("not allowed", encoding="utf-8")
w = ToolExecutor(extra_roots=[str(tmp)])
check("client root readable", "hello.txt" in w.list_dir(path=str(tmp)), "")
check("client root file readable",
      "from client workspace" in w.read_file(path=str(tmp / "hello.txt")), "")
check("relative resolves against primary", w.list_dir(path=".").startswith(str(w.workspace)))
check("unlisted root still blocked",
      w.read_file(path=str(other / "secret.txt")).startswith("[blocked]"))
check("roots include both", len(w.roots) >= 2, str(w.roots))

print("== backward compat: no extra roots ==")
w2 = ToolExecutor()
check("single root", len(w2.roots) == 1)
check("outside blocked", w2.list_dir(path="C:\\Windows").startswith("[blocked]"))

print()
print(f"TOTAL: {PASS} passed / {FAIL} failed")
sys.exit(1 if FAIL else 0)
