"""Can the V1 stream emit NATIVE tool_calls instead of prompt markup?

Root cause candidate for "feels very different from native Trae": gateway.py
render_tool_declarations injects tool docs into the PROMPT as text and asks the
model to emit markup
    <|FunctionCallBegin|>...<|FunctionCallEnd|>
That is a workaround, not the real mechanism - native Trae uses structured
tool_calls. The SSE `output` event already carries a real
"tool_calls": null field, so the protocol supports structured calls; we simply
never ask for them.

So: send tool schemas the way an OpenAI caller would, and see whether the
server ever returns tool_calls non-null. Any non-null hit means native calling
is reachable and the prompt hack can be dropped.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"}},
                       "required": ["city"]},
    },
}]

OUT_LIST: list[str] = []


def log(*a):
    OUT_LIST.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 240) -> str:
    return " ".join(t.split())[:n]


def tool_calls_seen(txt: str) -> list[str]:
    """Any structured tool_calls payload, or the prompt markup fallback."""
    structured = re.findall(r'"tool_calls"\s*:\s*(\[[^\]]*\]|null)', txt)
    non_null = [s for s in structured if s != "null"]
    markup = '<|FunctionCallBegin|>' in txt
    out = []
    if non_null:
        out.append(f"STRUCTURED x{len(non_null)}")
    if markup:
        out.append("PROMPT-MARKUP")
    return out or ["none"]


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = gw._headers()

    async def post(body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}/api/ide/v1/chat", json=body,
                                 headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    text = ("What is the weather in Beijing? You must call the "
            "get_weather tool.")
    sid = str(uuid.uuid4())
    base = {"user_input": text, "session_id": sid, "chat_history": [],
            "message_id": str(uuid.uuid4()),
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder",
                      "title": "Builder"}}

    log("=== A. tool request, no injections (does the server offer tools?) ===")
    code, txt = await post(dict(base))
    log(f"  -> {code} {tool_calls_seen(txt)}")
    log(f"     tail: {brief(txt[-260:], 260)}")

    log("\n=== B. try every plausible 'tools' field name ===")
    variants = {
        "tools=TOOLS": {"tools": TOOLS},
        "tool_specs": {"tool_specs": TOOLS},
        "available_tools": {"available_tools": TOOLS},
        "tool_declarations": {"tool_declarations": TOOLS},
        "function_declarations": {"function_declarations": TOOLS},
        "tool_list": {"tool_list": TOOLS},
        "agent_tools": {"agent_tools": TOOLS},
    }
    for label, extra in variants.items():
        code, txt = await post({**base, **extra})
        seen = tool_calls_seen(txt)
        note = "   <== MAYBE" if "STRUCTURED" in " ".join(seen) else ""
        log(f"  {label:22} -> {code} {seen}{note}")

    log("\n=== C. does any output event carry non-null tool_calls at all? ===")
    code, txt = await post({**base, "tools": TOOLS})
    for m in re.finditer(r'"tool_calls":\s*(\[[^\]]*\]|null)', txt):
        v = m.group(1)
        if v != "null":
            log(f"  NON-NULL: {v[:300]}")
    log("  (nothing above means every output had tool_calls:null)")

    try:
        io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs", "_nativetools.txt"), "w",
            encoding="utf-8").write("\n".join(OUT_LIST))
    except Exception:
        pass
    print("\n".join(OUT_LIST))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
