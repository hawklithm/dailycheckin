"""Probe Trae's newly-found 3.4.7 endpoints with our own credentials.

Targets (discovered in ai_agent.dll / harness.dll, absent in 3.4.4):
  POST /api/ide/v1/model_list
  POST /api/ide/v2/llm_raw_chat
  POST /api/v1/commercial/get_session_usage

Uses the same auth headers the proxy already uses for /api/ide/v1/chat.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import DEFAULT_BASE, TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    log(f"base: {gw.base}")
    log(f"user id: {getattr(auth, 'user_id', '?')}")

    async def call(path: str, body: dict, timeout: float = 45.0):
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{gw.base}{path}", json=body, headers=gw._headers())
            log(f"\n### POST {path}")
            log(f"  status: {r.status_code}")
            try:
                data = r.json()
                log("  body: " + json.dumps(data, ensure_ascii=False)[:2500])
            except Exception:
                log("  raw: " + r.text[:1200])
            return r

    # 1. model list - this alone would solve the "which model_name is legal" problem
    await call("/api/ide/v1/model_list", {"client_info": {"client_type": "ide"}})

    await call("/api/ide/v1/get_model_list", {})

    # 2. the raw chat endpoint
    await call("/api/ide/v2/llm_raw_chat", {
        "service": "chat", "method": "chat",
        "data": {
            "agent_type": "builder",
            "scene_location": 2,
            "agent": {"type": "builder", "name": "builder", "title": "Builder"},
            "model_name": "auto",
            "message_content": [{"type": "text", "text_content": "你好，请只回复两个字"}],
            "user_input": "你好，请只回复两个字",
        },
        "common_params": {"agent_type": "builder"},
        "client_info": {"client_type": "ide"},
    })

    # 3. session usage (billing)
    await call("/api/v1/commercial/get_session_usage",
               {"session_id": "00000000-0000-0000-0000-000000000000"})

    io.open("logs/_v2probe.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
