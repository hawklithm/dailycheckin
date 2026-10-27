"""Finish create_agent_task: nested user_input.id and onwards.

Progress:
    user_input is ideagent.UserInput (a struct)
    it needs user_input.id
Flat "user_input.id" as a key is not accepted - it must be a real nested
object. So the shape is {"user_input": {"id": ..., "text"/...: ...}}.

Continue the discovery with proper nesting, reading each named binding error
and building real nested objects. Record the full evolving payload so the
final working shape can be captured.
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


def set_path(obj: dict, dotted: str, value):
    """obj['a.b'] = value -> obj['a']['b'] = value"""
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
    url = f"{gw.base}/api/agent/v3/create_agent_task"

    sid = str(uuid.uuid4())
    text = "Reply with one word: pong"

    payload = {
        "conversation_id": sid,
        "session_id": sid,
        "user_id": auth.creds.user_id,
        "device_id": "4333646823299987",
        "agent_type": "solo_agent",
        "model_name": "deepseek-v4.1-flash",
        "config_name": "deepseek-v4.1-flash",
        "ide_version": "1.107.1",
        "user_input": {"id": str(uuid.uuid4()), "text": text,
                       "content": text, "query": text},
    }

    async def post(body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== iterative discovery with NESTED paths ===")
    for step in range(14):
        code, txt = await post(payload)
        log(f"\n  step{step}: http {code}")
        log(f"    {brief(txt, 300)}")

        m = re.search(r"expr_path=([\w\.\[\]]+), cause=([^\"}]+)", txt)
        g = re.search(r"Go struct field ([\w\.]+) of type ([\w\.\[\]\*]+)",
                      txt)
        if g:
            log(f"    !! TYPE: {g.group(1)} expects {g.group(2)}")
            break
        if not m:
            log("    -> no binding error: STOP (success or different error)")
            break
        path, cause = m.group(1), m.group(2)
        if "required" not in cause:
            log(f"    -> cause not 'required' ({cause[:50]}); stop")
            break
        # decide a plausible value from the field name
        leaf = path.split(".")[-1]
        if leaf.endswith("_id") or leaf == "id":
            val = sid if "session" in path or "conversation" in path \
                else str(uuid.uuid4())
        elif leaf in ("user_input", "text", "content", "query"):
            val = text
        elif leaf in ("agent_type",):
            val = "solo_agent"
        elif leaf in ("model_name", "config_name"):
            val = "deepseek-v4.1-flash"
        else:
            val = "x"
        before = json.dumps(payload, sort_keys=True)
        set_path(payload, path, val)
        if json.dumps(payload, sort_keys=True) == before:
            log(f"    !! {path} already set; stop")
            break
        log(f"    + set {path} = {val!r}")

    log("\n=== FINAL PAYLOAD ===")
    log(json.dumps(payload, indent=2, ensure_ascii=False)[:3000])

    code, txt = await post(payload, timeout=120)
    log(f"\n=== FINAL ATTEMPT: http {code} ===")
    log(brief(txt, 1500))

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_agenttask3.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
