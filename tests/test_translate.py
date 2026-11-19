"""Unit tests for the Trae->OpenAI tool-call translator."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.translate import (  # noqa: E402
    BEGIN, END, ToolCallTranslator, markup_from_tool_calls,
    normalize_messages, trae_history_and_input,
)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


def feed_all(t, chunks):
    text_out, calls_out = [], []
    for c in chunks:
        txt, calls = t.feed(c)
        if txt:
            text_out.append(txt)
        calls_out.extend(calls)
    residual, calls = t.finish()
    if residual:
        text_out.append(residual)
    calls_out.extend(calls)
    return "".join(text_out), calls_out


print("== basic extraction ==")
t = ToolCallTranslator()
markup = f'{BEGIN}[{{"name":"list_dir","parameters":{{"dir_path":"D:\\\\ws"}}}}]{END}'
text, calls = feed_all(t, ["before ", markup, " after"])
check("plain text preserved", text == "before  after", repr(text))
check("one call", len(calls) == 1)
check("name", calls and calls[0]["function"]["name"] == "list_dir")
check("arguments is JSON string", isinstance(calls[0]["function"]["arguments"], str))
check("arguments content", json.loads(calls[0]["function"]["arguments"]) == {"dir_path": "D:\\ws"})
check("id format", calls[0]["id"].startswith("call_"))
check("type", calls[0]["type"] == "function")

print("== markup split across chunks (worst case: marker byte-by-byte) ==")
t = ToolCallTranslator()
text, calls = feed_all(t, list(markup))
check("text empty", text.strip() == "", repr(text))
check("one call recovered", len(calls) == 1 and calls[0]["function"]["name"] == "list_dir")

print("== two calls in one markup (parallel) ==")
t = ToolCallTranslator()
two = f'{BEGIN}[{{"name":"a","parameters":{{}}}},{{"name":"b","parameters":{{"x":1}}}}]{END}'
text, calls = feed_all(t, [two])
check("two calls", len(calls) == 2, str(calls))
check("indices sequential", [c["index"] for c in calls] == [0, 1])

print("== text around calls in same chunk ==")
t = ToolCallTranslator()
mixed = f'看看: {BEGIN}[{{"name":"f","parameters":{{}}}}]{END} 完成'
text, calls = feed_all(t, [mixed])
check("prefix kept", text.startswith("看看: "), repr(text))
check("suffix kept", text.endswith(" 完成"), repr(text))
check("call found", len(calls) == 1 and calls[0]["function"]["name"] == "f")

print("== truncated call at stream end (lossless fallback) ==")
t = ToolCallTranslator()
text, calls = feed_all(t, [f"{BEGIN}[{{\"name\":\"f\""])
check("raw surfaced", BEGIN in text and "\"name\":\"f\"" in text, repr(text))
check("no phantom call", len(calls) == 0)

print("== unparseable payload kept raw ==")
t = ToolCallTranslator()
text, calls = feed_all(t, [f"{BEGIN}not-json{END}"])
check("raw kept", "not-json" in text, repr(text))
check("no call", len(calls) == 0)

print("== plain angle brackets untouched ==")
t = ToolCallTranslator()
text, calls = feed_all(t, ["if a < b and b > c: pass"])
check("no false positive", text == "if a < b and b > c: pass" and not calls, repr(text))

print("== normalize_messages: system preserved ==")
turns = normalize_messages([
    {"role": "system", "content": "You are a coding agent."},
    {"role": "user", "content": "hi"},
])
user_input, history = trae_history_and_input(turns)
check("system retained as compatibility text", "【系统指令】" in user_input and "coding agent" in user_input, user_input)
check("history has only final user turn", len(history) == 1 and history[0]["role"] == "user")

print("== normalize_messages: interleaved system/developer retained once ==")
turns = normalize_messages([
    {"role": "user", "content": "first"},
    {"role": "developer", "content": "DEVELOPER_SENTINEL"},
    {"role": "assistant", "content": "intermediate"},
    {"role": "system", "content": "LATE_SYSTEM_SENTINEL"},
    {"role": "user", "content": "last"},
])
user_input, history = trae_history_and_input(turns)
check("developer normalized", any(kind == "developer" for kind, _ in turns), str(turns))
check("late instructions attach to latest user", history[-1]["content"] == user_input and
      "DEVELOPER_SENTINEL" in user_input and "LATE_SYSTEM_SENTINEL" in user_input, user_input)
check("each instruction appears once", user_input.count("DEVELOPER_SENTINEL") == 1 and
      user_input.count("LATE_SYSTEM_SENTINEL") == 1, user_input)

print("== normalize_messages: assistant tool_calls -> markup ==")
turns = normalize_messages([
    {"role": "user", "content": "list files"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call_x", "type": "function",
         "function": {"name": "list_dir", "arguments": json.dumps({"dir_path": "D:\\ws"})}}
    ]},
    {"role": "tool", "tool_call_id": "call_x", "name": "list_dir", "content": "a.py\nb.md"},
])
user_input, history = trae_history_and_input(turns)
check("assistant turn re-marked", any(BEGIN in h["content"] and END in h["content"] for h in history), str(history))
check("tool result became user turn", history[-1]["role"] == "user" and "工具执行结果" in history[-1]["content"], str(history[-1]))
check("final user_input is the tool result", "工具执行结果" in user_input, user_input)
check("result content present", "a.py" in user_input)

print("== markup_from_tool_calls roundtrip ==")
m = markup_from_tool_calls([
    {"id": "call_1", "type": "function", "function": {"name": "run", "arguments": "{\"cmd\":\"ls\"}"}}
])
check("roundtrip parse", f'{BEGIN}[{{"name": "run"' in m or f'{{"name":"run"' in m.replace(" ", ""), m)
t = ToolCallTranslator()
text, calls = feed_all(t, [m])
check("rebuilt markup parses", len(calls) == 1 and calls[0]["function"]["name"] == "run")

print()
print(f"TOTAL: {PASS} passed / {FAIL} failed")
sys.exit(1 if FAIL else 0)
