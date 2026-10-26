"""Retry llm_raw_chat with REAL model names from /api/ide/v1/providers.

providers (code 0) gave the catalog. Try the first-party ones we know Trae ships:
  doubao-seed-2-1-pro-260628, doubao-seed-2-1-turbo-260628,
  deepseek-v4-pro, deepseek-v4-flash, glm-5.3, kimi-k3
and also try the v1 endpoint plus a couple of envelope tweaks per model.
"""
from __future__ import annotations

import asyncio
import io
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


MODELS = [
    "doubao-seed-2-1-turbo-260628",
    "doubao-seed-2-1-pro-260628",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "glm-5.3",
    "kimi-k3",
]


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = hdrs(auth.get_jwt(), auth.creds.token)

    async def post(path, body, label):
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            txt = r.text[:500]
            log(f"\n[{label}] -> {r.status_code}")
            log("   " + txt)
            return r
        except Exception as e:  # noqa: BLE001
            log(f"\n[{label}] -> ERR {type(e).__name__}: {e}")
            return None

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    cp = {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_name": "trae", "region": "CN", "app_version": "3.4.7",
          "package_type": "stable_cn", "agent_type": "builder"}
    ci = {"client_type": "ide", "device_id": "4333646823299987",
          "version_code": "20260212", "chat_mode": "code",
          "icube_language": "zh-CN"}

    for model in MODELS:
        body = {
            "service": "chat", "method": "chat",
            "user_info": u, "common_params": cp, "client_info": ci,
            "data": {
                "user_input": "hi",
                "message_content": [{"type": "text", "text_content": "hi"}],
                "model_name": model,
                "agent_type": "builder", "scene_location": 2,
                "agent": {"type": "builder", "name": "builder",
                          "title": "Builder"},
                "session_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()),
                "workspace_folders": [{"path": "D:\\workspace\\re_music",
                                       "name": "re_music"}],
            },
        }
        await post("/api/ide/v2/llm_raw_chat", body, f"v2 {model}")

    io.open("logs/_realmodels.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
