"""super_completion_query names the model it uses - can we steer that?

probe_v2_chat found that /api/ide/v1/super_completion_query returns a metadata
event naming the model actually serving the request, e.g.
    event: meta data: {"id":"...","model":"S-CodeFusionContext-Query", ...}
That is concrete proof the server honours model selection for this principal -
something /api/ide/v1/chat never reveals (its metadata event has model:"").

If any parameter can steer that model, we learn the server's model-routing
vocabulary, which is exactly what llm_raw_chat was supposed to give us.

Approach: replay the request and try candidate model/function knobs, watching
the metadata.model field for any change from the default.
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
MODEL_RE = re.compile(r'"model"\s*:\s*"([^"]*)"')


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


def brief(t: str, n: int = 220) -> str:
    return " ".join(t.split())[:n]


def models_in(txt: str) -> list[str]:
    return MODEL_RE.findall(txt)


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)
    PATH = "/api/ide/v1/super_completion_query"

    async def post(body, timeout=60):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{PATH}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    base = {"user_input": "hi", "session_id": str(uuid.uuid4())}

    log("=== baseline: what model does it pick by itself? ===")
    code, txt = await post(dict(base))
    base_models = models_in(txt)
    log(f"  -> {code} models={base_models} {brief(txt, 200)}")

    log("\n=== try to steer it ===")
    trials = {
        "model_name=deepseek-v4.1-flash": {"model_name":
                                           "deepseek-v4.1-flash"},
        "model_name=deepseek-v4-flash": {"model_name": "deepseek-v4-flash"},
        "model=S-CodeFusionContext-Query": {"model":
                                            "S-CodeFusionContext-Query"},
        "function=chat": {"function": "chat"},
        "raw_chat_function=chat": {"raw_chat_function": "chat"},
        "custom_model": {"custom_model": {
            "config_name": "deepseek-v4.1-flash",
            "model_name": "deepseek-v4.1-flash"}},
        "model_auto_selection": {"model_auto_selection":
                                 {"strategy": "manual"}},
    }
    for label, extra in trials.items():
        code, txt = await post({**base, **extra})
        ms = models_in(txt)
        changed = ms != base_models
        flag = "   <== MODEL CHANGED" if changed else ""
        log(f"  {label:34} -> {code} models={ms} {brief(txt,120)}{flag}")

    log("\n=== other endpoints: does metadata reveal the model? ===")
    chat_body = {"user_input": "Reply pong", "session_id": str(uuid.uuid4()),
                 "chat_history": [],
                 "message_content": [{"type": "text",
                                      "text_content": "Reply pong"}],
                 "message_id": str(uuid.uuid4()),
                 "agent_type": "builder", "scene_location": 2,
                 "agent": {"type": "builder", "name": "builder",
                           "title": "Builder"}}
    for p in ("/api/ide/v1/chat", "/api/ide/v1/fast_apply",
              "/api/ide/v1/super_completion_query"):
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{gw.base}{p}", json=chat_body, headers=H)
            ms = models_in(r.text)
            log(f"  {p:38} -> {r.status_code} models={ms}")
        except Exception as e:  # noqa: BLE001
            log(f"  {p:38} -> ERR {e}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_modelsteer.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
