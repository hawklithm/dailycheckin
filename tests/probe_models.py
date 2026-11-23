"""Use /api/ide/v1/providers (code 0!) to get real model names, then retry
llm_raw_chat with a real model_name instead of "auto".

providers returned code 0 with entries like
  {"id":"deepseek","models":["deepseek-v4-pro","deepseek-v4-flash"],
   "model_detail":[{"model_name":"deepseek-v4-pro","display_name":"DeepSeek-V4-Pro"}]}
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def hdrs(jwt, cloudide):
    trace = uuid.uuid4().hex[:16]
    return {
        "Authorization": f"Cloud-IDE-JWT {jwt}",
        "x-cloudide-token": cloudide,
        "content-type": "application/json",
        "accept": "*/*",
        "accept-language": "zh-CN",
        "app-version": "3.4.7",
        "package-type": "stable_cn",
        "user-agent": "VSCode 1.107.1 (Trae CN)",
        "vscode-sessionid": "56cb66e60ecd32141cfe256f4e5ff76e7f8d53bc99c6a93f8ef48b7cb0068524",
        "x-request-id": str(uuid.uuid4()),
        "x-tt-trace-id": f"00-{trace}{trace[:8]}-{trace}-01",
        "x-user-region": "CN",
        "x-lgw-req-sdk-type": "3",
        "x-lscbd-aid": "787976",
        "x-lscbd-platform": "windows",
    }


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = hdrs(auth.get_jwt(), auth.creds.token)

    async def post(path, body, label):
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            txt = r.text[:900]
            log(f"\n[{label}] {path} -> {r.status_code}")
            log("   " + txt)
            return r
        except Exception as e:  # noqa: BLE001
            log(f"\n[{label}] {path} -> ERR {type(e).__name__}: {e}")
            return None

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    cp = {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_name": "trae", "region": "CN", "app_version": "3.4.7",
          "package_type": "stable_cn"}
    ci = {"client_type": "ide", "device_id": "4333646823299987",
          "version_code": "20260212", "chat_mode": "code"}

    # 1. full providers dump
    r = await post("/api/ide/v1/providers",
                   {"service": "model", "method": "providers",
                    "user_info": u, "common_params": cp, "client_info": ci},
                   "providers")
    models = []
    if r is not None:
        try:
            d = r.json()
            for p in d.get("providers") or []:
                log(f"\n  provider {p.get('id')}: {p.get('models')}")
                for md in p.get("model_detail") or []:
                    models.append(md.get("model_name"))
        except Exception:
            pass
    log(f"\n=== model names seen: {models} ===")

    # 2. retry llm_raw_chat with a real model name
    def body_for(model_name: str):
        return {
            "service": "chat", "method": "chat",
            "user_info": u,
            "common_params": {**cp, "agent_type": "builder"},
            "client_info": ci,
            "data": {
                "user_input": "hi",
                "message_content": [{"type": "text", "text_content": "hi"}],
                "model_name": model_name,
                "agent_type": "builder", "scene_location": 2,
                "agent": {"type": "builder", "name": "builder",
                          "title": "Builder"},
                "session_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()),
                "workspace_folders": [{"path": "D:\\workspace\\re_music",
                                       "name": "re_music"}],
            },
        }

    for m in (models or ["deepseek-v4-flash"])[:3]:
        await post("/api/ide/v2/llm_raw_chat", body_for(m), f"llm_raw_chat {m}")

    io.open("logs/_models.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
