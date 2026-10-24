"""E2E agent-loop verification against the running proxy (turn 2: tool result)."""
import json
import sys
import urllib.request


def chat(messages, stream=False):
    body = json.dumps({"model": "x", "messages": messages, "stream": stream}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8080/v1/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=150) as r:
        return json.loads(r.read().decode("utf-8"))


messages = [
    {"role": "user", "content": "请用 list_dir 工具查询 D:\\workspace\\trae2api 目录"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call_test001", "type": "function",
         "function": {"name": "list_dir", "arguments": json.dumps({"dir_path": "D:\\workspace\\trae2api"})}}
    ]},
    {"role": "tool", "tool_call_id": "call_test001", "name": "list_dir",
     "content": "main.py\nREADME.md\nnotes/\ntrae2api/"},
]

r2 = chat(messages)
msg2 = r2["choices"][0]["message"]
out = {
    "turn2_finish": r2["choices"][0]["finish_reason"],
    "answer_head": msg2["content"][:220],
    "leak_check": ("<|" in msg2["content"]),
    "usage": r2.get("usage"),
}
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
