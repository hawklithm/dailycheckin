"""Retry llm_raw_chat with the chat_mode result folded into the request.

/api/v1/commercial/chat_mode returns 200 with
  {"mode_list":[{"default_status":true,"mode_type":1,"trae_request_type":0,...}]}
so the server does have our app config - the 2001 "record not found" is about a
specific key. trae_request_type and mode_type are the obvious candidates to
echo back in common_params / client_info / data.
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


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = hdrs(auth.get_jwt(), auth.creds.token)

    async def post(path, body, label):
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            log(f"\n[{label}] -> {r.status_code}")
            log("   " + r.text[:600])
            return r
        except Exception as e:  # noqa: BLE001
            log(f"\n[{label}] -> ERR {type(e).__name__}: {e}")
            return None

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}

    def envelope(extra_cp=None, extra_ci=None, extra_data=None):
        cp = {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
              "app_name": "trae", "region": "CN", "app_version": "3.4.7",
              "package_type": "stable_cn", "agent_type": "builder"}
        cp.update(extra_cp or {})
        ci = {"client_type": "ide", "device_id": "4333646823299987",
              "version_code": "20260212", "icube_language": "zh-CN",
              "chat_mode": "code"}
        ci.update(extra_ci or {})
        d = {
            "user_input": "hi",
            "message_content": [{"type": "text", "text_content": "hi"}],
            "model_name": "auto",
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder", "title": "Builder"},
            "session_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "workspace_folders": [{"path": "D:\\workspace\\re_music",
                                   "name": "re_music"}],
        }
        d.update(extra_data or {})
        return {"service": "chat", "method": "chat", "user_info": u,
                "common_params": cp, "client_info": ci, "data": d}

    await post("/api/ide/v2/llm_raw_chat", envelope(),
               "baseline (real headers)")
    await post("/api/ide/v2/llm_raw_chat",
               envelope(extra_cp={"mode_type": 1, "trae_request_type": 0}),
               "+mode_type/trae_request_type in common_params")
    await post("/api/ide/v2/llm_raw_chat",
               envelope(extra_ci={"mode_type": 1, "trae_request_type": 0}),
               "+mode_type/trae_request_type in client_info")
    await post("/api/ide/v2/llm_raw_chat",
               envelope(extra_data={"mode_type": 1, "trae_request_type": 0}),
               "+mode_type/trae_request_type in data")
    await post("/api/ide/v2/llm_raw_chat",
               envelope(extra_cp={"product_type": "ide",
                                  "trae_request_type": 0}),
               "+product_type")
    await post("/api/ide/v2/llm_raw_chat",
               envelope(extra_cp={"app_config_id": "default",
                                  "config_id": "default"}),
               "+app_config_id")

    io.open("logs/_mode2.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
