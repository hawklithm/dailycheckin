"""Verify the shell/pwsh fix against the exact calls from the debug log."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.tools import ToolExecutor  # noqa: E402

e = ToolExecutor(extra_roots=[r"D:\workspace\re_music"])

CASES = [
    ("log call #1 (PowerShell, no cwd)",
     {"command": "Get-ChildItem -Path 'D:\\workspace\\re_music' -Depth 2 | "
                 "Select-Object FullName, PSIsContainer | Format-Table -AutoSize"}),
    ("log call #2 (cwd + Get-ChildItem -Force)",
     {"command": "Get-ChildItem -Force", "cwd": r"D:\workspace\re_music"}),
    ("shell alias via run()",
     None),
    ("cmd-style (dir /b)",
     {"command": "dir /b", "cwd": r"D:\workspace\re_music"}),
    ("plain echo",
     {"command": "echo hello"}),
]

for label, kw in CASES:
    print("=" * 20, label, "=" * 20)
    if kw is None:
        out = e.run("shell", '{"command":"Get-ChildItem -Force","cwd":"D:\\\\workspace\\\\re_music"}')
    else:
        out = e.run_command(**kw)
    print((out or "")[:400])
    print()
