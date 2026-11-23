"""Diff our llm_raw_chat request against the V1 request that provably works.

Both calls succeed at the transport/auth layer against the same host, yet V1
streams real tokens while llm_raw_chat answers 4011 before parsing the body
(minimal body proves this). We are therefore missing something in the request
metadata - most likely a header or an identity knob.

This emits the exact headers and body of both requests side by side so the
difference can be inspected rather than guessed.
"""
from __future__ import annotations

import asyncio
import io
import json
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
    L = legacy(auth.get_jwt(), auth.creds.region)
    V1 = gw._headers()

    sid = str(uuid.uuid4())
    text = "Reply with one word: pong"

    log("=== header set comparison ===")
    keys = sorted(set(L) | set(V1))
    log(f"  {'header':28} {'legacy(4011)':22} {'v1(works)':22}")
    for k in keys:
        a = L.get(k, "-")
        b = V1.get(k, "-")
        mark = "  <== DIVERGES" if a != b else ""
        # truncate secrets
        a = (a[:18] + "...") if len(a) > 22 else a
        b = (b[:18] + "...") if len(b) > 22 else b
        log(f"  {k:28} {a:22} {b:22}{mark}")

    async def post(path, body, headers, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body,
                                 headers=headers)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    flat = {"user_input": text, "session_id": sid, "chat_history": [],
            "message_content": [{"type": "text", "text_content": text}],
            "message_id": str(uuid.uuid4()),
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder",
                      "title": "Builder"}}

    log("\n=== A. V1 headers -> llm_raw_chat (cross test) ===")
    code, txt = await post("/api/ide/v2/llm_raw_chat", flat, V1)
    log(f"  v1 headers -> rawchat -> {code} [{verdict(txt)}] {brief(txt,150)}")

    log("\n=== B. V1 headers -> V1 chat (control) ===")
    code, txt = await post("/api/ide/v1/chat", flat, V1)
    log(f"  v1 headers -> v1chat  -> {code} [{verdict(txt)}] {brief(txt,120)}")

    log("\n=== C. V1 body keys sent to raw_chat / absent from ours ===")
    body_v1 = gw.build_chat_body("auto", [{"role": "user", "content": text}],
                                 session_id=sid)
    log("  build_chat_body keys: " + ", ".join(sorted(body_v1)))
    log("  raw_chat flat keys:   " + ", ".join(sorted(flat)))
    only_v1 = sorted(set(body_v1) - set(flat))
    log(f"  only in V1 body: {only_v1}")

    log("\n=== D. replay EXACT V1 body to raw_chat, V1 headers ===")
    code, txt = await post("/api/ide/v2/llm_raw_chat", dict(body_v1), V1)
    v = verdict(txt)
    log(f"  -> {code} [{v}] {brief(txt, 200)}")

    log("\n=== E. V1 body + legacy headers -> raw_chat ===")
    code, txt = await post("/api/ide/v2/llm_raw_chat", dict(body_v1), L)
    log(f"  -> {code} [{verdict(txt)}] {brief(txt, 200)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_v1diff.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
