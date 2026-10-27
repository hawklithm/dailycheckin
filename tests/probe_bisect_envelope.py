"""Bisect by SUBTRACTION: flat body works, envelope fails. Find the poison field.

Facts:
  flat  body -> STREAM OK
  envelope   -> 3003 "all models failed"
Same headers, same user, same prompt, same model fields (or none). So a field
PRESENT ONLY in the envelope is breaking model dispatch.

Envelope adds: service, data{...}, user_info, client_info, common_params,
streamlined_common_params. Note `data` nesting is itself a suspect: on the flat
body the chat fields sit at top level; in the envelope they are nested under
"data", and the server may be reading the model fields from top level only.

Approach: start from the WORKING flat body and add envelope pieces one at a
time. The first addition that breaks it is the culprit.
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


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 110) -> str:
    return " ".join(t.split())[:n]


def outcome(txt: str) -> str:
    if "output" in txt and "token_usage" in txt:
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

    text = "Reply with one word: pong"
    sid = str(uuid.uuid4())
    ws = ["D:\\workspace\\re_music"]

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    ci = {"chat_session_id": sid, "device_id": "4333646823299987",
          "client_type": "ide", "workspace_folders": ws,
          "version_code": "20260212", "workspace_folder": ws[0],
          "icube_language": "zh-CN", "user_timezone": "Asia/Shanghai",
          "is_solo_mode": False, "window_type": "desktop"}
    cp = {"code_window_type": "desktop", "agent_type": "builder",
          "app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_version": "3.4.7", "region": "CN"}

    async def post(body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}/api/ide/v1/chat", json=body,
                                 headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    # exactly the body the gateway sends today (proven working)
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

    log("=== additive bisect from the WORKING flat body ===")
    code, txt = await post(dict(flat))
    log(f"  0. flat baseline                -> {outcome(txt)}")

    adds = [
        ("1. +service", {"service": "chat"}),
        ("2. +service+method", {"service": "chat", "method": "chat"}),
        ("3. +user_info", {"user_info": u}),
        ("4. +common_params", {"common_params": cp}),
        ("5. +streamlined", {"streamlined_common_params": cp}),
        ("6. +client_info", {"client_info": ci}),
        ("7. +all envelope bits",
         {"service": "chat", "method": "chat", "user_info": u,
          "common_params": cp, "streamlined_common_params": cp,
          "client_info": ci}),
    ]
    for label, extra in adds:
        code, txt = await post({**flat, **extra})
        log(f"  {label:32} -> {outcome(txt)}   {brief(txt, 80)}")

    log("\n=== now the nesting question: data{...} wrapper ===")
    # same fields, but nested under "data" the way the envelope does it
    nested = {"service": "chat", "method": "chat", "data": dict(flat),
              "user_info": u, "common_params": cp,
              "streamlined_common_params": cp, "client_info": ci}
    code, txt = await post(dict(nested))
    log(f"  all fields nested in data       -> {outcome(txt)}")

    # nested data but chat fields ALSO mirrored at top level
    mirrored = {**nested, **flat}
    code, txt = await post(mirrored)
    log(f"  nested + mirrored at top level  -> {outcome(txt)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_bisect_env.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
