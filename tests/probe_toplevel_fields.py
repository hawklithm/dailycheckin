"""Put the REAL ChatArgs fields at TOP LEVEL and see if capability unlocks.

Established: this HTTP endpoint reads chat fields from the TOP LEVEL of the
body; wrapping them in `data` breaks model selection with 3003. The flat body
we send works but yields tool_calls:null and prompt-injected tools.

Therefore the untested and most promising move is: keep the flat shape, but
add the ChatArgs fields the real sidecar uses - at top level. Those include
several capability switches we have never sent:

    native_function_call (in ModelExtraConfig), force_tool_calls,
    use_file_context, workspace_context, code_selections, dsl_agent,
    is_solo_mode, command_type, model_auto_selection, context_window_size,
    active_text_editor, unit_test_functions, code_language_environment

If any of these flips tool_calls from null to structured, native tool calling
becomes available and the prompt-injection workaround can go away.
"""
from __future__ import annotations

import asyncio
import io
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


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 120) -> str:
    return " ".join(t.split())[:n]


def structured_tools(txt: str) -> bool:
    for m in re.finditer(r'"tool_calls"\s*:\s*(\[[^\]]*\]|null)', txt):
        if m.group(1) != "null":
            return True
    return False


def outcome(txt: str) -> str:
    if "token_usage" in txt:
        return "STREAM OK"
    m = re.search(r'"code":(\d+)', txt)
    if m:
        return f"code={m.group(1)}"
    return "other"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = gw._headers()

    text = ("What is the weather in Beijing? Use the get_weather tool.")
    sid = str(uuid.uuid4())
    ws = ["D:\\workspace\\re_music"]

    flat = {
        "user_input": text,
        "session_id": sid,
        "chat_history": [],
        "message_content": [{"type": "text", "text_content": text}],
        "message_id": str(uuid.uuid4()),
        "agent_type": "builder",
        "scene_location": 2,
        "agent": {"type": "builder", "name": "builder", "title": "Builder"},
        "workspace_folders": ws,
    }

    async def post(body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}/api/ide/v1/chat", json=body,
                                 headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== baseline ===")
    code, txt = await post(dict(flat))
    log(f"  flat            -> {outcome(txt)} structured={structured_tools(txt)}")

    log("\n=== add real ChatArgs capability fields at TOP LEVEL ===")
    trials = {
        "+native_function_call": {"native_function_call": True},
        "+force_tool_calls": {"force_tool_calls": True},
        "+tools": {"tools": TOOLS},
        "+tools+nfc": {"tools": TOOLS, "native_function_call": True},
        "+use_file_context": {"use_file_context": True},
        "+workspace_context": {"workspace_context": {
            "active_file": "", "visible_files": []}},
        "+code_selections": {"code_selections": []},
        "+dsl_agent": {"dsl_agent": None},
        "+is_solo_mode": {"is_solo_mode": True},
        "+command_type": {"command_type": None},
        "+model_auto_selection": {"model_auto_selection":
                                  {"strategy": "auto"}},
        "+context_window_size": {"context_window_size": 200000},
        "+code_language_environment": {"code_language_environment":
                                       "python"},
        "+turn_id/origin": {"turn_id": str(uuid.uuid4()), "origin": "ide"},
        "+ALL": {
            "native_function_call": True, "force_tool_calls": True,
            "tools": TOOLS, "use_file_context": True,
            "code_selections": [], "is_solo_mode": True,
            "model_auto_selection": {"strategy": "auto"},
            "context_window_size": 200000,
            "code_language_environment": "python",
            "turn_id": str(uuid.uuid4()), "origin": "ide",
        },
    }
    for label, extra in trials.items():
        code, txt = await post({**flat, **extra})
        st = structured_tools(txt)
        flag = "   <== STRUCTURED TOOLS!" if st else ""
        log(f"  {label:26} -> {outcome(txt):11} structured={st}{flag}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_toplevel_fields.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
