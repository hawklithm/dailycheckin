"""Break into api/agent/v3/create_agent_task - the real agent-mode entry.

HUGE find: POST {gateway}/api/agent/v3/create_agent_task is NOT 404, it answers

    400 {"code":4001,
         "message":"bad request: binding: expr_path=conversation_id,
                    cause=missing required parameter"}

That is a structured validation error naming the exact missing field. The
server is telling us what to send. This is the agent-mode entry point that
should produce the rich 28-event stream (tool_call / thought / turn_completion).

Strategy: iteratively satisfy the binding errors. Each error names
expr_path=<field>, so add that field and repeat. conversation_id first, then
whatever it asks for next.
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
URL = None


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 400) -> str:
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
    url = f"{gw.base}/api/agent/v3/create_agent_task"

    sid = str(uuid.uuid4())
    ws = ["D:\\workspace\\re_music"]
    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    ci = {"chat_session_id": sid, "device_id": "4333646823299987",
          "client_type": "ide", "workspace_folders": ws,
          "version_code": "20260212", "workspace_folder": ws[0],
          "icube_language": "zh-CN", "user_timezone": "Asia/Shanghai"}
    cp = {"agent_type": "solo_agent", "code_window_type": "desktop",
          "app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_version": "3.4.7", "region": "CN"}

    text = "Reply with one word: pong"

    async def post(body, timeout=60):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    # Start minimal and let the server name each missing field.
    payload: dict = {}
    log("=== iterative binding discovery ===")
    for attempt in range(8):
        code, txt = await post(dict(payload))
        log(f"\n  attempt {attempt}: http {code}")
        log(f"    {brief(txt, 500)}")
        m = re.search(r"expr_path=([A-Za-z0-9_.\[\]]+)", txt)
        if not m:
            # not a binding error any more - stop and report
            log("    -> no further binding error; stopping")
            break
        missing = m.group(1)
        # supply a plausible value for the named field
        if missing in payload:
            log(f"    !! already provided {missing}; stopping to avoid loop")
            break
        if "id" in missing.lower() or missing.endswith("_id"):
            payload[missing] = sid
        elif missing in ("user_input", "query", "content", "message"):
            payload[missing] = text
        elif missing in ("agent_type",):
            payload[missing] = "solo_agent"
        else:
            payload[missing] = "x"
        log(f"    -> adding {missing}={payload[missing]!r}")

    log("\n=== now try with a fuller, realistic body ===")
    full = {
        "conversation_id": sid,
        "session_id": sid,
        "chat_session_id": sid,
        "message_id": str(uuid.uuid4()),
        "user_input": text,
        "message_content": [{"type": "text", "text_content": text}],
        "agent_type": "solo_agent",
        "workspace_folders": ws,
        "scene_location": 2,
        "user_info": u,
        "client_info": ci,
        "common_params": cp,
        "streamlined_common_params": cp,
    }
    code, txt = await post(full, timeout=90)
    log(f"  -> http {code}")
    log(f"    {brief(txt, 800)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_agenttask.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
