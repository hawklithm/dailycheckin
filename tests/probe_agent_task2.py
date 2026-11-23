"""Finish breaking into create_agent_task by honouring the Go struct errors.

The server is a Go service and it is now type-checking us:

    cannot unmarshal string into Go struct field
    CreateAgentTaskRequest.user_input of type ideagent.UserInput

That is enormously informative:
  * the request struct is named CreateAgentTaskRequest
  * user_input is NOT a string, it is ideagent.UserInput (a struct)
  * the error format "Go struct field X.Y of type Z" leaks BOTH the struct and
    the field's Go type for every field we get wrong

So we can enumerate the real schema field-by-field by deliberately sending a
wrong type and reading the type the server names back. This script does that
for every candidate field, then assembles a correct request.
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
    text = "Reply with one word: pong"

    # the required scalars the server already named
    base = {
        "conversation_id": sid,
        "session_id": sid,
        "user_id": auth.creds.user_id,
        "device_id": "4333646823299987",
        "agent_type": "solo_agent",
        "model_name": "deepseek-v4.1-flash",
        "config_name": "deepseek-v4.1-flash",
        "ide_version": "1.107.1",
    }

    async def post(body, timeout=60):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== A. probe the Go type of each interesting field ===")
    # send a deliberately wrong scalar (number) and read back the Go type
    probe_fields = [
        "user_input", "message_content", "workspace_folders", "client_info",
        "common_params", "user_info", "agent", "tools", "chat_history",
        "scene_location", "custom_model", "model_info", "query",
    ]
    types: dict[str, str] = {}
    for f in probe_fields:
        body = {**base, f: 12345}   # wrong type on purpose
        code, txt = await post(body)
        m = re.search(r"Go struct field (\w+)\.(\w+) of type ([\w\.\[\]\*]+)",
                      txt)
        if m:
            types[f] = m.group(3)
            log(f"  {f:20} -> {m.group(3)}")
        else:
            m2 = re.search(r"expr_path=([\w\.]+), cause=([^\"}]+)", txt)
            if m2:
                log(f"  {f:20} -> (binding) {m2.group(1)}: "
                    f"{m2.group(2)[:60]}")
            else:
                log(f"  {f:20} -> {brief(txt, 110)}")

    log("\n=== B. build user_input as an object (ideagent.UserInput) ===")
    ui_variants = {
        "text": {"text": text},
        "content": {"content": text},
        "text_content": {"text_content": text},
        "query": {"query": text},
        "value": {"value": text},
        "message": {"message": text},
    }
    for label, ui in ui_variants.items():
        body = {**base, "user_input": ui}
        code, txt = await post(body)
        m = re.search(r"expr_path=([\w\.]+)", txt)
        g = re.search(r"Go struct field (\w+)\.(\w+) of type ([\w\.]+)", txt)
        status = "?"
        if m:
            status = f"needs {m.group(1)}"
        elif g:
            status = f"type: {g.group(3)}"
        else:
            status = brief(txt, 130)
        log(f"  user_input={label:14} -> http {code}  {status}")

    log("\n=== C. whatever it asks for next, keep going ===")
    payload = {**base, "user_input": {"text": text}}
    for i in range(6):
        code, txt = await post(payload)
        m = re.search(r"expr_path=([\w\.]+), cause=([^\"}]+)", txt)
        g = re.search(r"Go struct field (\w+)\.(\w+) of type ([\w\.]+)", txt)
        log(f"  step{i}: http {code} {brief(txt, 200)}")
        if m:
            f = m.group(1)
            if f in payload:
                log("    (already set - stop)")
                break
            payload[f] = text if "input" in f else sid
            log(f"    + {f}")
        elif g:
            log(f"    !! type mismatch on {g.group(2)} expected {g.group(3)}")
            break
        else:
            break

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_agenttask2.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
