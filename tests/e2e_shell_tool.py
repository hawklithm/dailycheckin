"""E2E: force the model to use a `shell` tool call and check it actually ran.

This reproduces the DSH session where the bridge logged "执行工具: shell" and
then executed nothing. The client here is DSH-shaped: it declares no tools of
its own (so every gateway tool call must be executed locally by the bridge) and
puts its cwd in the runtime-context snapshot.
"""
import json
import sys
import urllib.request

WORKSPACE = r"D:\workspace\re_music"

snapshot = (
    "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n"
    f'Current working directory: "{WORKSPACE}".\n'
    "Current DSH file policy: danger-full-access."
)
messages = [
    {"role": "user", "content": snapshot},
    {"role": "user", "content": (
        "用 shell 工具执行一条 PowerShell 命令，列出当前工作目录下所有以 .md 结尾的文件名"
        "（用 Get-ChildItem 加 Select-Object 实现），然后只回答这些文件名。"
        "必须真的调用工具，不要凭猜测回答。"
    )},
]
body = json.dumps({"model": "x", "messages": messages, "stream": False}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8080/v1/chat/completions", data=body, method="POST",
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=280) as r:
    d = json.loads(r.read().decode("utf-8"))
m = d["choices"][0]["message"]
out = {"finish": d["choices"][0]["finish_reason"], "answer": m["content"][:400]}
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
