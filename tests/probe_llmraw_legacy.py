"""Confirm llm_raw_chat now clears the app-config error with legacy headers.

probe_header_matrix found that with the LEGACY device header set (the one
Trae's own completion.log shows for get_detail_param), v2/llm_raw_chat answers
4011 "requests have exceeded the rate limit" instead of the long-standing
2001 "failed to get app config: record not found".

4011 is a different failure mode entirely: the request got past auth and
config lookup. This script re-runs it several times to make sure it is
reproducible and not a one-off, and tries to push past it.
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
    }


def brief(t: str, n: int = 260) -> str:
    return " ".join(t.split())[:n]


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    jwt = auth.get_jwt()
    H = dict(legacy(jwt, auth.creds.region))
    H["Accept"] = "text/event-stream"

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    cp = {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_name": "trae", "region": "CN", "app_version": "3.4.7",
          "package_type": "stable_cn"}
    ci = {"client_type": "ide", "device_id": "4333646823299987",
          "version_code": "20260212", "chat_mode": "code"}

    def body_for(model, msgs=None):
        return {
            "service": "chat", "method": "chat", "user_info": dict(u),
            "common_params": {**cp, "agent_type": "solo_agent"},
            "client_info": dict(ci),
            "data": {
                "user_input": "hi",
                "message_content": msgs or [{"type": "text",
                                             "text_content": "hi"}],
                "model_name": model, "config_name": model,
                "agent_type": "solo_agent",
                "scene_location": 2,
                "session_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()),
                "workspace_folders": [{"path": "D:\\workspace\\re_music",
                                       "name": "re_music"}],
            },
        }

    async def post(path, body, timeout=120):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== repeat v2/llm_raw_chat with legacy headers (repro check) ===")
    codes: dict[str, int] = {}
    for i in range(5):
        code, txt = await post("/api/ide/v2/llm_raw_chat",
                               body_for("deepseek-v4.1-flash"))
        key = None
        for k in ("2001", "4011", "4001", "4023"):
            if k in txt:
                key = k
                break
        codes[key or f"http{code}"] = codes.get(key or f"http{code}", 0) + 1
        log(f"  run{i}: {key or 'http'+str(code):8} {brief(txt, 150)}")
    log(f"  summary: {codes}")

    log("\n=== v1/llm_raw_chat (same headers) ===")
    code, txt = await post("/api/ide/v1/llm_raw_chat",
                           body_for("deepseek-v4.1-flash"))
    log(f"  -> {code} {brief(txt, 240)}")

    log("\n=== try alternate models (no model / doubao / glm) ===")
    for m in ("", "auto", "Doubao-Seed-2.1-Turbo", "glm-5.3-flash",
              "deepseek-v4.1-flash"):
        code, txt = await post("/api/ide/v2/llm_raw_chat", body_for(m))
        flag = "" if ("4011" in txt or "2001" in txt) else "   <== DIFFERENT"
        log(f"  model={m:26} -> {code} {brief(txt, 190)}{flag}")

    io.open("logs/_breakthrough.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
