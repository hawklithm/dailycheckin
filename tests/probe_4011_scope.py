"""Pin down what 4011 actually means for llm_utils_chat.

Evidence so far: llm_utils_chat returns
    "no function config found for appId=..., function=X"   for agent/code/summary
    4011 rate limit                                        for solo_agent/builder/
                                                           chat/inline_chat
so config exists for the latter group. But is 4011 a real quota, a per-function
counter, or something about the request shape?

Tests:
  A. Same function twice with a fresh session - is it stable?
  B. Vary fields that might affect quota accounting: mode_type, is_custom_model,
     agent_type, model/config name, provider.
  C. Compare against v1/chat (which still streams fine) - if v1/chat works
     while llm_utils_chat 4011s for the same account at the same moment, the
     limit is endpoint/function scoped, not account scoped.
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


def brief(t: str, n: int = 260) -> str:
    return " ".join(t.split())[:n]


def kind(txt: str) -> str:
    if "exceeded the rate limit" in txt:
        return "4011-limit"
    if "no function config found" in txt:
        return "no-config"
    if "token_usage" in txt:
        return "STREAM OK"
    m = re.search(r'"code":(\d+),"error":"","message":"([^"]{0,40})', txt)
    if m:
        return f"{m.group(1)}:{m.group(2)[:30]}"
    m2 = re.search(r'"message":"([^"]{0,50})', txt)
    return m2.group(1)[:40] if m2 else "other"


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

    text = "Reply with one word: pong"

    def p(**extra):
        sid = str(uuid.uuid4())
        b = {"user_input": text, "conversation_id": sid, "session_id": sid,
             "user_id": auth.creds.user_id,
             "device_id": "4333646823299987", "ide_version": "1.107.1",
             "function": "solo_agent"}
        b.update(extra)
        return b

    async def post(path, body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    LU = "/api/agent/v3/llm_utils_chat"

    log("=== A. stability: same call 3x, fresh session each ===")
    for i in range(3):
        code, txt = await post(LU, p())
        log(f"  run{i} -> {code} {kind(txt)}")

    log("\n=== B. vary accounting-relevant fields ===")
    variants = {
        "baseline": {},
        "mode_type=0": {"mode_type": 0},
        "mode_type=1": {"mode_type": 1},
        "is_custom_model=false": {"is_custom_model": False},
        "agent_type=solo_agent": {"agent_type": "solo_agent"},
        "model+config": {"model_name": "deepseek-v4.1-flash",
                         "config_name": "deepseek-v4.1-flash"},
        "provider=": {"provider": ""},
        "require_multimodel=false": {"require_multimodel": False},
    }
    for label, extra in variants.items():
        code, txt = await post(LU, p(**extra))
        log(f"  {label:26} -> {code} {kind(txt)}")

    log("\n=== C. same moment: v1/chat vs llm_utils_chat ===")
    v1 = {"user_input": text, "session_id": str(uuid.uuid4()),
          "chat_history": [],
          "message_content": [{"type": "text", "text_content": text}],
          "message_id": str(uuid.uuid4()),
          "agent_type": "builder", "scene_location": 2,
          "agent": {"type": "builder", "name": "builder", "title": "Builder"}}
    c1, t1 = await post("/api/ide/v1/chat", v1)
    log(f"  v1/chat            -> {c1} {kind(t1)}")
    c2, t2 = await post(LU, p())
    log(f"  llm_utils_chat     -> {c2} {kind(t2)}")
    log("\n  -> if v1 streams while llm_utils 4011s at the same instant,")
    log("     the limit is endpoint/function scoped, not account scoped.")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_4011_scope.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
