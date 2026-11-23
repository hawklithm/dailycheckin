"""Find which denylist pattern matches a given command."""
import sys

sys.path.insert(0, ".")
from trae2api.tools import DANGER  # noqa: E402

cmd = sys.argv[1] if len(sys.argv) > 1 else (
    "Get-ChildItem -Path 'D:\\workspace\\re_music' -Depth 2 | "
    "Select-Object FullName, PSIsContainer | Format-Table -AutoSize")
print("cmd:", cmd[:150])
for rx in DANGER:
    m = rx.search(cmd)
    if m:
        print("MATCHED:", rx.pattern)
        print("  text:", repr(m.group(0))[:140])
print("done")
