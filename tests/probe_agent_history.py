"""Break the last barrier: "missing history count exceeded for session".

Progress chain on create_agent_task:
    config item is empty  -> (config key now satisfied) ->
    code 4000105 "missing history count exceeded for session <id>"

The config lookup SUCCEEDS now. What remains is session state: the server
counts how many times it had to reconstruct missing history for a session and
gives up after a threshold. Our sweep reused ONE session id for 60+ calls, so
we tripped that counter ourselves.

Fix: a FRESH session id per attempt, plus a proper history/initialize handshake.
The local route table had chat.initialize and api/v1/chat/initialize, and
query_history_state / sync_history_state exist on agent/v3 - so the intended
order is likely:
    initialize -> start_chat/create_agent_task (with history) -> subscribe

This tries fresh sessions and a minimal history payload.
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


def brief(t: str, n: int = 320) -> str:
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


def classify(txt: str) -> str:
    if "missing history count exceeded" in txt:
        return "HISTORY-LIMIT"
    if "config item is empty" in txt:
        return "CONFIG-EMPTY"
    if "missing required parameter" in txt:
        m = re.search(r"expr_path=([\w\.]+)", txt)
        return f"NEED:{m.group(1) if m else '?'}"
    if "token_usage" in txt or '"response"' in txt:
        return "STREAM!"
    m = re.search(r'"code":(\d+),"error":"","message":"([^"]{0,50})', txt)
    if m:
        return f"E{m.group(1)}:{m.group(2)[:40]}"
    return "other"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)
    url = f"{gw.base}/api/agent/v3/create_agent_task"

    text = "Reply with one word: pong"

    async def post(u, body, timeout=60):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(u, json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    def make(fn="solo_agent", cfg="deepseek-v4.1-flash", mode=1,
             history=None, extra=None):
        sid = str(uuid.uuid4())
        body = {
            "conversation_id": sid, "session_id": sid,
            "user_id": auth.creds.user_id,
            "device_id": "4333646823299987",
            "agent_type": "solo_agent", "model_name": cfg,
            "config_name": cfg, "ide_version": "1.107.1",
            "mode_type": mode,
            "user_input": {"id": str(uuid.uuid4()), "text": text},
        }
        if history is not None:
            body["history"] = history
            body["chat_history"] = history
        if extra:
            body.update(extra)
        return body

    log("=== A. fresh session each time (no shared history counter) ===")
    variants = {
        "bare": make(),
        "empty history": make(history=[]),
        "one user msg": make(history=[{"role": "user", "content": text}]),
        "message_content": make(extra={
            "message_content": [{"type": "text", "text_content": text}]}),
        "mode=0": make(mode=0),
    }
    for label, body in variants.items():
        code, txt = await post(url, body)
        log(f"  {label:20} -> {code} {classify(txt):22} {brief(txt, 130)}")

    log("\n=== B. initialize first, then create_agent_task ===")
    sid = str(uuid.uuid4())
    init_body = {
        "conversation_id": sid, "session_id": sid,
        "user_id": auth.creds.user_id,
        "device_id": "4333646823299987",
        "ide_version": "1.107.1",
    }
    for init_path in ("/api/v1/chat/initialize",
                      "/api/agent/v3/query_history_state"):
        code, txt = await post(f"{gw.base}{init_path}", init_body)
        log(f"  init {init_path:32} -> {code} {classify(txt)} "
            f"{brief(txt, 120)}")

    body = make()
    body["conversation_id"] = sid
    body["session_id"] = sid
    code, txt = await post(url, body)
    log(f"  then create_agent_task -> {code} {classify(txt)} "
        f"{brief(txt, 200)}")

    log("\n=== C. try sync_history_state / resume paths ===")
    for p, b in (
            ("/api/agent/v3/sync_history_state",
             {"conversation_id": sid, "session_id": sid,
              "user_id": auth.creds.user_id,
              "device_id": "4333646823299987", "history": []}),
            ("/api/agent/v3/resume_agent_task",
             {"conversation_id": sid, "session_id": sid,
              "user_id": auth.creds.user_id,
              "device_id": "4333646823299987"}),
            ("/api/agent/v3/llm_utils_chat",
             {"conversation_id": sid, "session_id": sid,
              "user_id": auth.creds.user_id,
              "device_id": "4333646823299987",
              "user_input": {"id": str(uuid.uuid4()), "text": text}})):
        code, txt = await post(f"{gw.base}{p}", b, timeout=90)
        log(f"  {p:42} -> {code} {classify(txt)}")
        log(f"      {brief(txt, 220)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_history.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
