"""Complete llm_utils_chat: supply `function` so it can resolve a model.

The endpoint now streams and asks only:

    [LLMUtilsChat.resolveByUsage] function is empty, cannot resolve model by
    usage=

So it needs a `function` value to pick a model by usage. Candidate values come
from what we have already seen the server use as Function:
    solo_agent (from the create_agent_task config key), builder, chat, agent

Once function resolves, this becomes a clean single-prompt LLM call over SSE -
exactly the "standard ability" the user asked for, and it should emit the rich
event stream rather than the v1/chat 3-event subset.
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


def events(txt: str) -> list[str]:
    return re.findall(r"^event:\s*(\S+)", txt, re.M)


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
    url = f"{gw.base}/api/agent/v3/llm_utils_chat"

    text = "Reply with one word: pong"

    def payload(**extra):
        sid = str(uuid.uuid4())
        p = {
            "user_input": text,
            "conversation_id": sid,
            "session_id": sid,
            "user_id": auth.creds.user_id,
            "device_id": "4333646823299987",
            "ide_version": "1.107.1",
        }
        p.update(extra)
        return p

    async def post(body, timeout=120):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== A. supply `function` (candidates from observed Function values) ===")
    for fn in ("solo_agent", "builder", "chat", "agent", "code",
               "inline_chat", "summary"):
        code, txt = await post(payload(function=fn))
        ev = events(txt)
        ok = "token_usage" in txt
        msg = ""
        m = re.search(r'"message":"([^"]{0,90})', txt)
        if m:
            msg = m.group(1)
        log(f"  function={fn:14} -> {code} events={ev} "
            f"{'*** STREAM OK ***' if ok else msg}")
        if ok:
            log("      " + brief(txt, 700))

    log("\n=== B. function + model/config name ===")
    for fn in ("solo_agent", "builder", "chat"):
        for cfg in ("deepseek-v4.1-flash", "auto"):
            code, txt = await post(payload(function=fn, model_name=cfg,
                                           config_name=cfg))
            ok = "token_usage" in txt
            m = re.search(r'"message":"([^"]{0,80})', txt)
            log(f"  fn={fn:12} cfg={cfg:22} -> {code} "
                f"{'*** STREAM OK ***' if ok else (m.group(1) if m else '?')}")

    log("\n=== C. raw event list from the best attempt ===")
    code, txt = await post(payload(function="solo_agent"))
    log(f"  events: {events(txt)}")
    log("  --- first 1500 chars ---")
    log(txt[:1500])

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_llmutils2.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
