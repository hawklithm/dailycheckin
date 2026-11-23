"""Pursue api/agent/v3/llm_utils_chat - the closest thing to a plain LLM call.

Findings so far:
    /api/agent/v3/llm_utils_chat exists and answers:
      4001 "cannot unmarshal object into Go struct field
            LLMUtilsChatRequest.user_input of type string"
    i.e. its request struct is LLMUtilsChatRequest and user_input is a STRING
    here (unlike create_agent_task where it is ideagent.UserInput).

Also confirmed:
    /api/agent/v3/sync_history_state -> 200 {"message":"History state synced
        successfully"}   (works!)
    /api/agent/v3/query_history_state -> needs history_id_list
    /api/agent/v3/resume_agent_task   -> needs task_id

llm_utils_chat is attractive because it takes a plain string prompt, which is
exactly the "standard ability" the user asked for. This drives it to success
using the same iterative binding discovery that worked before.
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


def brief(t: str, n: int = 500) -> str:
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


def set_path(obj, dotted, value):
    parts = dotted.split(".")
    cur = obj
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)
    url = f"{gw.base}/api/agent/v3/llm_utils_chat"

    text = "Reply with one word: pong"
    sid = str(uuid.uuid4())

    payload = {
        "user_input": text,           # a STRING per the type error
        "conversation_id": sid,
        "session_id": sid,
        "user_id": auth.creds.user_id,
        "device_id": "4333646823299987",
        "ide_version": "1.107.1",
    }

    async def post(body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== iterative binding discovery on LLMUtilsChatRequest ===")
    for step in range(16):
        code, txt = await post(payload)
        log(f"\n  step{step}: http {code}")
        log(f"    {brief(txt, 400)}")

        m = re.search(r"expr_path=([\w\.\[\]]+), cause=([^\"}]+)", txt)
        g = re.search(r"Go struct field ([\w\.]+) of type ([\w\.\[\]\*]+)",
                      txt)
        if g:
            log(f"    !! TYPE: {g.group(1)} expects {g.group(2)}")
            fld = g.group(1).split(".")[-1]
            if "UserInput" in g.group(2):
                # it wants a struct - but we already send a string...
                log("    -> wants struct, retrying with nested object")
                set_path(payload, fld, {"id": str(uuid.uuid4()),
                                        "text": text})
                continue
            break
        if not m:
            log("    -> no binding error; STOP")
            break
        path = m.group(1)
        if "required" not in m.group(2):
            log("    -> non-required cause; stop")
            break
        leaf = path.split(".")[-1]
        if leaf.endswith("_id") or leaf == "id":
            val = sid
        elif leaf in ("user_input", "text", "content", "query", "prompt"):
            val = text
        elif leaf in ("model_name", "config_name"):
            val = "deepseek-v4.1-flash"
        elif leaf == "agent_type":
            val = "solo_agent"
        elif leaf == "ide_version":
            val = "1.107.1"
        else:
            val = "x"
        before = json.dumps(payload, sort_keys=True)
        set_path(payload, path, val)
        if json.dumps(payload, sort_keys=True) == before:
            log(f"    !! {path} already set; stop")
            break
        log(f"    + set {path} = {val!r}")

    log("\n=== FINAL PAYLOAD ===")
    log(json.dumps(payload, indent=2, ensure_ascii=False)[:2000])

    code, txt = await post(payload, timeout=120)
    log(f"\n=== FINAL: http {code} ===")
    log(brief(txt, 2000))

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_llmutils.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:9000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
