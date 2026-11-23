"""Verify the real chat transport: api/v1/chat/* instead of api/ide/v1/chat.

Decompilation found a whole endpoint family we never touched:

    api/v1/chat/initialize
    api/v1/chat/start_chat
    api/v1/chat/start_resume_chat
    api/v1/chat/subscribe_events     <-- likely the 28-event stream
    api/v1/chat/append_msg
    api/v1/chat/revert_message
    api/v1/chat/stop_chat
    api/v1/chat/delete_message
    api/v1/chat/dislike_message

Note the shape: these are verbs, and subscribe_events is a SEPARATE call from
start_chat. That is a completely different protocol from
"POST api/ide/v1/chat and read one SSE stream": you start a chat, then
subscribe to its events - which is exactly how you would get task_created /
thought / tool_call / turn_completion.

This probes each endpoint with legacy headers to learn which exist and what
they want.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import uuid
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []

PATHS = [
    "initialize", "start_chat", "start_resume_chat", "subscribe_events",
    "append_msg", "revert_message", "stop_chat", "delete_message",
    "dislike_message",
]


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 260) -> str:
    return " ".join(t.split())[:n]


def legacy(jwt, region):
    return {
        "X-App-Id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
        "x-plugin-channel": "icube-ai",
        "x-ide-version-code": "20260212",
        "x-ide-token": jwt,
        "Content-Type": "application/json",
        "Authorization": f"Cloud-IDE-JWT {jwt}",
        "X-Device-Cpu": "AMD",
        "X-Device-Id": "4333646823299987",
        "X-Machine-Id": "56cb66e60ecd32141cfe256f4e5ff76e7f8d53bc99c6a93f8ef48b7cb0068524",
        "X-Device-Brand": "MS-7B89",
        "X-Device-Type": "windows",
        "X-Os-Version": quote("Windows 10 Education"),
        "X-User-Region": region or "CN",
        "Accept": "text/event-stream",
    }


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)

    async def post(path, body, timeout=45):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    sid = str(uuid.uuid4())
    ws = ["D:\\workspace\\re_music"]
    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    ci = {"chat_session_id": sid, "device_id": "4333646823299987",
          "client_type": "ide", "workspace_folders": ws,
          "version_code": "20260212", "workspace_folder": ws[0]}
    cp = {"agent_type": "builder", "code_window_type": "desktop",
          "app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_version": "3.4.7", "region": "CN"}

    log("=== probe api/v1/chat/* (empty body first, to learn existence) ===")
    for p in PATHS:
        path = f"/api/v1/chat/{p}"
        code, txt = await post(path, {})
        note = ""
        if code == 404:
            note = "  (no route)"
        elif code == 200:
            note = "  <== EXISTS"
        log(f"  {path:34} -> {code} {brief(txt, 160)}{note}")

    log("\n=== start_chat with a real-ish envelope ===")
    text = "Reply with one word: pong"
    body = {
        "service": "chat", "method": "start_chat",
        "user_info": u, "client_info": ci, "common_params": cp,
        "streamlined_common_params": cp,
        "data": {
            "user_input": text,
            "message_content": [{"type": "text", "text_content": text}],
            "workspace_folders": ws, "scene_location": 2,
            "agent_type": "builder", "session_id": sid,
            "message_id": str(uuid.uuid4()),
        },
    }
    for p in ("start_chat", "initialize"):
        code, txt = await post(f"/api/v1/chat/{p}", body, timeout=90)
        log(f"\n  {p} -> {code}")
        log(f"    {brief(txt, 600)}")

    log("\n=== subscribe_events (after start_chat attempt) ===")
    code, txt = await post("/api/v1/chat/subscribe_events",
                           {"session_id": sid, "chat_session_id": sid},
                           timeout=30)
    log(f"  -> {code} {brief(txt, 400)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_v1chat_family.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
