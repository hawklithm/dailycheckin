"""E2E: builder mode with a DSH-shaped request (cwd in user snapshot + tools)."""
import json
import sys
import urllib.request

snapshot = (
    "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n"
    'Current working directory: "D:\\workspace\\trae2api".\n'
    "Current DSH file policy: danger-full-access."
)
messages = [
    {"role": "user", "content": snapshot},
    {"role": "user", "content": "看一下 trae2api 目录下有哪些文件，然后告诉我 tests 目录里有多少个 .py 文件"},
]
tools = [
    {"type": "function", "function": {"name": "list_dir", "description": "列出目录",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "执行命令",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]
body = json.dumps({"model": "x", "messages": messages, "tools": tools, "stream": False}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8080/v1/chat/completions", data=body, method="POST",
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=250) as r:
    d = json.loads(r.read().decode("utf-8"))
m = d["choices"][0]["message"]
out = {"finish": d["choices"][0]["finish_reason"], "answer": m["content"][:280]}
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
