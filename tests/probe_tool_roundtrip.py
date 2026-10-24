"""Capture tool-call round-trip: send a tool call result back and record the wire format.

Phase 1: send user prompt -> model emits <|FunctionCallBegin|>...<|FunctionCallEnd|>
Phase 2: send the SAME session_id with chat_history containing the assistant turn
         (with the function call markup) + a tool result in various candidate shapes,
         and record which one the server accepts (no 4001) and how the model reacts.
"""
import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.auth import TraeAuth
from trae2api.gateway import TraeGateway


def parse_events(raw: bytes) -> list[tuple[str, dict]]:
    events = []
    event = None
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            try:
                payload = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                payload = {"raw": line[5:].strip()}
            events.append((event or "", payload))
            event = None
    return events


def collect(raw: bytes) -> dict:
    content_parts, reasoning_parts, events, usage, done = [], [], [], {}, None
    for name, data in parse_events(raw):
        events.append(name)
        if name == "output":
            if data.get("response"):
                content_parts.append(data["response"])
            if data.get("reasoning_content"):
                reasoning_parts.append(data["reasoning_content"])
        elif name == "token_usage":
            usage = data
        elif name == "done":
            done = data
        elif name == "error":
            done = {"error": data}
    return {
        "events": events,
        "content": "".join(content_parts),
        "reasoning": "".join(reasoning_parts)[:200],
        "usage": usage,
        "done": done,
    }


async def run_stream(g: TraeGateway, body: dict) -> bytes:
    chunks = []
    async with g.client.stream("POST", f"{g.base}/api/ide/v1/chat", json=body,
                               headers=g._headers()) as r:
        if r.status_code != 200:
            raw = await r.aread()
            return f"HTTP {r.status_code}: {raw[:200]!r}".encode()
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)
    return b"".join(chunks)


async def main() -> None:
    a = TraeAuth()
    a.load()
    g = TraeGateway(a)
    sid = str(uuid.uuid4())

    out = {"session_id": sid}

    # ---- Phase 1: provoke a tool call ----
    body1 = g.build_chat_body("", [{"role": "user", "content": "请用工具 list_dir 查询 D:\\workspace\\trae2api 目录下的文件列表"}])
    body1["session_id"] = sid
    raw1 = await run_stream(g, body1)
    p1 = collect(raw1)
    out["phase1"] = p1
    print("=== PHASE 1 (provoke tool call) ===")
    print("events:", p1["events"])
    print("content:", repr(p1["content"][:400]))
    print("reasoning:", repr(p1["reasoning"][:200]))
    print()

    assistant_content = p1["content"]
    if "<|FunctionCallBegin|>" not in assistant_content:
        print("!! model did not emit a function call; dumping full content for inspection")
        print(assistant_content)
        # still continue with whatever we got

    # ---- Phase 2: reply with a tool result in candidate shapes ----
    tool_result_text = "file_a.py\nfile_b.md\nnotes/\ntrae2api/"

    variants = {}

    # Variant A: assistant turn carries the raw markup; user turn wraps result in a guess-marker
    variants["A_user_plain"] = [
        {"role": "user", "content": "请用工具 list_dir 查询 D:\\workspace\\trae2api 目录下的文件列表"},
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": f"工具执行结果：\n{tool_result_text}\n请根据结果继续回答。"},
    ]

    # Variant B: chat_history with explicit function role (OpenAI style)
    variants["B_function_role"] = [
        {"role": "user", "content": "请用工具 list_dir 查询 D:\\workspace\\trae2api 目录下的文件列表"},
        {"role": "assistant", "content": assistant_content},
        {"role": "function", "name": "list_dir", "content": tool_result_text},
    ]

    # Variant C: tool role (OpenAI style)
    variants["C_tool_role"] = [
        {"role": "user", "content": "请用工具 list_dir 查询 D:\\workspace\\trae2api 目录下的文件列表"},
        {"role": "assistant", "content": assistant_content},
        {"role": "tool", "name": "list_dir", "content": tool_result_text},
    ]

    # Variant D: assistant turn + user turn with Trae-ish markers
    variants["D_markers"] = [
        {"role": "user", "content": "请用工具 list_dir 查询 D:\\workspace\\trae2api 目录下的文件列表"},
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": f"<|FunctionCallBegin|>[{{\"name\":\"list_dir\",\"parameters\":{{\"dir_path\":\"D:\\\\workspace\\\\trae2api\"}}}}]<|FunctionCallEnd|> 的执行结果：\n{tool_result_text}"},
    ]

    for name, history in variants.items():
        # note: build_chat_body extracts user_input from LAST user message and
        # rebuilds chat_history from earlier turns, so we bypass it to control
        # the exact chat_history shape.
        last_user = next((m for m in reversed(history) if m["role"] == "user"), None)
        body = {
            "user_input": last_user["content"] if last_user else "continue",
            "session_id": sid,
            "chat_history": history[:-1] if last_user else history,
            "intent_name": "chat",
        }
        try:
            raw = await run_stream(g, body)
            if raw.startswith(b"HTTP "):
                p = {"events": [], "content": raw.decode("utf-8", "replace"), "reasoning": "", "usage": None, "done": None}
            else:
                p = collect(raw)
            out[f"phase2_{name}"] = p
            print(f"--- Phase 2 variant {name} ---")
            print("events:", p["events"][:8])
            print("content:", repr(p["content"][:250]))
            print("done/error:", p["done"])
            print()
        except Exception as e:
            print(f"--- Phase 2 variant {name} EXC: {e}")
            out[f"phase2_{name}"] = {"exception": str(e)}
        await asyncio.sleep(2)

    os.makedirs("notes", exist_ok=True)
    with open("notes/tooluse-roundtrip-capture.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved: notes/tooluse-roundtrip-capture.json")


if __name__ == "__main__":
    asyncio.run(main())
