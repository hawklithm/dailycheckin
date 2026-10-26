"""Try llm_raw_chat with chat_mode / app-config identifiers.

The 2001 error is "failed to get app config: record not found". The renderer's
plugin API calls all carry chat_mode=code, and ai_agent.dll exposes
api/ide/v1/commercial/get_mode_info and api/ide/v1/chat_mode.

So the app config is probably keyed by (product, chat_mode, package_type) or
similar. Try adding those to the request, and also probe get_mode_info.
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
        "x-market-client-id": "VSCode 1.107.1",
    }


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = hdrs(auth.get_jwt(), auth.creds.token)

    async def post(path, body, label):
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            log(f"\n[{label}] {path} -> {r.status_code}")
            log("   " + r.text[:400])
            return r
        except Exception as e:  # noqa: BLE001
            log(f"\n[{label}] {path} -> ERR {type(e).__name__}: {e}")
            return None

    base_user = {"user_id": auth.creds.user_id, "user_type": "user",
                 "user_is_login": True, "device_id": "4333646823299987"}

    # 1. get_mode_info / chat_mode first - they may reveal the config key
    for path, body in [
        ("/api/ide/v1/commercial/get_mode_info", {
            "service": "commercial", "method": "get_mode_info",
            "user_info": base_user,
            "common_params": {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                              "app_version": "3.4.7", "region": "CN"},
            "client_info": {"client_type": "ide", "version_code": "20260212"},
        }),
        ("/api/ide/v1/chat_mode", {
            "service": "commercial", "method": "chat_mode",
            "user_info": base_user,
            "common_params": {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                              "app_version": "3.4.7", "region": "CN"},
            "client_info": {"client_type": "ide", "version_code": "20260212"},
        }),
    ]:
        await post(path, body, path.rsplit("/", 1)[-1])

    # 2. llm_raw_chat with chat_mode / app identifiers added
    variants = [
        ("+chat_mode in common_params", {"chat_mode": "code"}),
        ("+chat_mode+product", {"chat_mode": "code", "product": "ide",
                                "product_name": "ide"}),
        ("+app_config_id", {"app_config_id": "default"}),
        ("+config_name", {"config_name": "default"}),
    ]
    for label, extra in variants:
        cp = {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
              "app_name": "trae", "region": "CN", "app_version": "3.4.7",
              "agent_type": "builder"}
        cp.update(extra)
        body = {
            "service": "chat", "method": "chat",
            "user_info": base_user,
            "common_params": cp,
            "client_info": {"client_type": "ide", "device_id": "4333646823299987",
                            "version_code": "20260212", "icube_language": "zh-CN",
                            "chat_mode": extra.get("chat_mode", "code")},
            "data": {
                "user_input": "hi",
                "message_content": [{"type": "text", "text_content": "hi"}],
                "model_name": "auto",
                "agent_type": "builder", "scene_location": 2,
                "agent": {"type": "builder", "name": "builder", "title": "Builder"},
                "session_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()),
                "chat_type": extra.get("chat_mode", "code"),
                "workspace_folders": [{"path": "D:\\workspace\\re_music",
                                       "name": "re_music"}],
            },
        }
        await post("/api/ide/v2/llm_raw_chat", body, label)

    io.open("logs/_modeinfo.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
