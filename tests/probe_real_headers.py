"""Retry llm_raw_chat / model_list with real Trae headers.

Our earlier probes sent the header set from gateway.py (X-App-Id, X-Device-*,
x-ide-token, trae-cn/3.4.4 UA). The captured renderer traffic to api.trae.cn
uses a different set: app-version, package-type, vscode-sessionid,
x-request-id, x-tt-trace-id, x-cloudide-token, and a VSCode UA.

The 4001 might be a header/version gate rather than a body problem, so retry
with the real set before concluding the body is wrong.
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
from trae2api.gateway import DEFAULT_BASE, TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def real_headers(jwt: str, cloudide: str) -> dict:
    """Headers modelled on the captured renderer traffic."""
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
    jwt = auth.get_jwt()
    cloudide = auth.creds.token

    log(f"base: {gw.base}")
    log(f"jwt len {len(jwt)}, cloudide len {len(cloudide)}")

    async def post(path, body, headers, label):
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=headers)
            txt = r.text[:400]
            log(f"\n[{label}] {path} -> {r.status_code}")
            log("   " + txt)
            return r
        except Exception as e:  # noqa: BLE001
            log(f"\n[{label}] {path} -> ERR {type(e).__name__}: {e}")
            return None

    hdrs = real_headers(jwt, cloudide)
    log("\n=== real-style headers ===")
    for k, v in hdrs.items():
        vv = v if len(v) < 70 else v[:67] + "..."
        log(f"  {k}: {vv}")

    # model_list with real headers
    await post("/api/ide/v1/model_list", {
        "service": "model", "method": "get_model_list",
        "user_info": {"user_id": auth.creds.user_id, "user_type": "user",
                      "user_is_login": True, "device_id": "4333646823299987"},
        "common_params": {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                          "app_name": "trae", "region": "CN",
                          "app_version": "3.4.7"},
        "client_info": {"client_type": "ide", "device_id": "4333646823299987",
                        "version_code": "20260212"},
    }, hdrs, "model_list real-headers")

    # llm_raw_chat with real headers
    chat_body = {
        "service": "chat", "method": "chat",
        "user_info": {"user_id": auth.creds.user_id, "user_type": "user",
                      "user_is_login": True, "device_id": "4333646823299987"},
        "common_params": {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                          "app_name": "trae", "region": "CN",
                          "app_version": "3.4.7", "agent_type": "builder"},
        "client_info": {"client_type": "ide", "device_id": "4333646823299987",
                        "version_code": "20260212", "icube_language": "zh-CN"},
        "data": {
            "user_input": "hi",
            "message_content": [{"type": "text", "text_content": "hi"}],
            "model_name": "auto",
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder", "title": "Builder"},
            "session_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "workspace_folders": [{"path": "D:\\workspace\\re_music",
                                   "name": "re_music"}],
        },
    }
    await post("/api/ide/v2/llm_raw_chat", chat_body, hdrs, "llm_raw_chat v2 real-headers")

    # also with the ORIGINAL gateway headers but adding app-version/package-type
    gh = dict(gw._headers())
    gh["app-version"] = "3.4.7"
    gh["package-type"] = "stable_cn"
    gh["user-agent"] = "VSCode 1.107.1 (Trae CN)"
    gh["vscode-sessionid"] = "56cb66e60ecd32141cfe256f4e5ff76e7f8d53bc99c6a93f8ef48b7cb0068524"
    gh["x-request-id"] = str(uuid.uuid4())
    gh["x-tt-trace-id"] = "00-" + uuid.uuid4().hex[:16] + "-01"
    await post("/api/ide/v2/llm_raw_chat", chat_body, gh, "llm_raw_chat v2 mixed-headers")

    io.open("logs/_realhdr.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
