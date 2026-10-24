"""Streaming tool-call extraction check: capture full content + tool_calls."""
import json
import sys
import urllib.request

body = json.dumps({
    "model": "x",
    "messages": [{"role": "user", "content": "必须调用 list_dir 工具，参数 dir_path=D:\\workspace\\trae2api。不要直接回答。"}],
    "stream": True,
}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8080/v1/chat/completions", data=body, method="POST",
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=150) as r:
    events = 0
    tool_calls = []
    finish = None
    content = []
    reasoning = []
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:") or "[DONE]" in line:
            continue
        try:
            chunk = json.loads(line[5:])
        except json.JSONDecodeError:
            continue
        if not isinstance(chunk, dict) or not chunk.get("choices"):
            continue  # error payload or keep-alive
        d = chunk["choices"][0]
        events += 1
        delta = d.get("delta", {})
        if delta.get("tool_calls"):
            tool_calls.extend(delta["tool_calls"])
        if d.get("finish_reason"):
            finish = d["finish_reason"]
        if delta.get("content"):
            content.append(delta["content"])
        if delta.get("reasoning_content"):
            reasoning.append(delta["reasoning_content"])

out = {
    "events": events,
    "finish": finish,
    "tool_calls": [{"name": tc["function"]["name"], "args": tc["function"]["arguments"]} for tc in tool_calls],
    "content_head": "".join(content)[:120],
    "content_leak": "<|" in "".join(content),
    "reasoning_head": "".join(reasoning)[:80],
}
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
