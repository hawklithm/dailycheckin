"""Is there a /api/ide/v2/chat (the external twin of internal llm_raw_chat)?

llm_raw_chat never appears anywhere in the client's plaintext logs (0 grep
hits), while its string occurs only 15x inside ai_agent.dll in sidecar log
messages like "[LLMAdapter] llm_raw_chat_custom_model request". That pattern
fits an INTERNAL sidecar->server channel rather than the public chat entry,
which would explain a permanent 4011 for us no matter how we shape it.

So probe for the v2 sibling of the endpoint we know works (v1/chat). If
v2/chat exists it is very likely the real path, and it should accept the flat
V1 body we already proved good.
"""
from __future__ import annotations

import asyncio
import io
import os
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


def brief(t: str, n: int = 200) -> str:
    return " ".join(t.split())[:n]


def verdict(txt: str) -> str:
    for k in ("2001", "4011", "4001", "4023"):
        if k in txt:
            return k
    if "token_usage" in txt or '"response"' in txt:
        return "STREAM!"
    return "other"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)

    text = "Reply with one word: pong"
    body = {"user_input": text, "session_id": str(uuid.uuid4()),
            "chat_history": [],
            "message_content": [{"type": "text", "text_content": text}],
            "message_id": str(uuid.uuid4()),
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder",
                      "title": "Builder"}}

    async def post(path, b, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=b, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== 0. control: known-good v1/chat ===")
    code, txt = await post("/api/ide/v1/chat", body)
    log(f"  /api/ide/v1/chat      -> {code} [{verdict(txt)}] {brief(txt,120)}")

    log("\n=== 1. hunt for a v2 chat sibling ===")
    cands = [
        "/api/ide/v2/chat", "/api/ide/v2/agent/chat",
        "/api/ide/v2/chat/completions", "/api/ide/v2/raw_chat",
        "/api/ide/v2/llm_chat", "/api/ide/v2/stream_chat",
        "/api/ide/v2/message", "/api/ide/v2/conversation",
    ]
    for p in cands:
        code, txt = await post(p, body)
        v = verdict(txt)
        note = ""
        if code == 404:
            note = "(404 no route)"
        elif v not in ("4011", "4001"):
            note = "   <== INTERESTING"
        log(f"  {p:32} -> {code} [{v:7}] {brief(txt, 110)}{note}")

    log("\n=== 2. does raw_chat accept the V1 body at all? (reflex check) ===")
    code, txt = await post("/api/ide/v2/llm_raw_chat", body)
    log(f"  v2/llm_raw_chat       -> {code} [{verdict(txt)}] {brief(txt,120)}")

    log("\n=== 3. other documented v1 endpoints for completeness ===")
    for p in ("/api/ide/v1/super_completion", "/api/ide/v1/fast_apply",
              "/api/ide/v1/chat_prompt", "/api/ide/v1/connect",
              "/api/ide/v1/super_completion_query"):
        code, txt = await post(p, body)
        log(f"  {p:32} -> {code} [{verdict(txt):7}] {brief(txt, 100)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_v2chat.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
