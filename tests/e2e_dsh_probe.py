"""Reproduce a real DSH turn: 31 declared tools, ask for a shell command.

Purpose: capture what the gateway actually returns when the client declares
tools. If it returns `pwsh` (a name DSH declared) instead of `shell`, the
bridge classifies it as a client call and never executes it.
"""
import json
import sys
import time
import urllib.request

DSH_TOOLS = ["ask_user_question", "create_goal", "edit", "exit_plan_mode", "get_goal",
             "glob", "grep", "interrupt_agent", "job_kill", "job_list", "job_output",
             "list_agents", "present", "pwsh", "read", "read_image", "schedule_create",
             "schedule_delete", "schedule_list", "schedule_update", "send_message",
             "skill", "subagent", "subagent_fork", "todo_write", "update_goal",
             "web_fetch", "web_search", "workflow", "working_directory", "write"]

tools = [{"type": "function", "function": {"name": n, "description": n,
          "parameters": {"type": "object", "properties": {}}}} for n in DSH_TOOLS]

messages = [
    {"role": "user", "content": (
        'Current working directory: "D:\\workspace\\re_music".\n'
        "Current DSH file policy: danger-full-access.")},
    {"role": "user", "content":
        "列出当前目录下所有 .md 文件。必须真的调用工具执行，不要凭猜测回答。"},
]
body = json.dumps({"model": "deepseek-v4.1-flash", "messages": messages,
                   "tools": tools, "stream": True}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8080/v1/chat/completions", data=body, method="POST",
    headers={"Content-Type": "application/json"})

t0 = time.time()
with urllib.request.urlopen(req, timeout=280) as r:
    raw = r.read()

text = raw.decode("utf-8", "replace")
out = {
    "seconds": round(time.time() - t0, 1),
    "has_tool_calls_chunk": "tool_calls" in text,
    "has_执行工具": "执行工具" in text,
    "raw_first_3000": text[:3000],
}
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
