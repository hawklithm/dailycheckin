"""Attack the 2001 "failed to get app config: record not found".

Observations to exploit:
1. The DLL packs a SECOND uuid next to ours near the endpoint table:
   api/ide/v1/get_resource_url <6eefa01c-...> <850edec7-b9d0-48aa-99b5-67c888e282cd>
   We always send 6eefa01c. Try 850edec7 too.
2. The create_agent_task log shows: function=?, config_name=?, model_name=?
   so data may need a `function` and/or `config_name` to select the app config.
3. /api/ide/v1/get_custom_model_type_config returned {"message":"success"} with
   no payload, and batch_get_detail_param had function_configs: [] - both
   consistent with "the config record does not exist for our identity".
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
APP_A = "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"
APP_B = "850edec7-b9d0-48aa-99b5-67c888e282cd"


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def hdrs(jwt, cloudide, app_id):
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
        "x-app-id": app_id,
    }


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    jwt, cloudide = auth.get_jwt(), auth.creds.token

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}

    async def post(path, body, hdr, label):
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=hdr)
            log(f"\n[{label}] -> {r.status_code} {r.text[:300]}")
            return r
        except Exception as e:  # noqa: BLE001
            log(f"\n[{label}] -> ERR {type(e).__name__}: {e}")
            return None

    def chat(app_id, extra_data=None, extra_cp=None):
        cp = {"app_id": app_id, "app_name": "trae", "region": "CN",
              "app_version": "3.4.7", "package_type": "stable_cn",
              "agent_type": "builder"}
        cp.update(extra_cp or {})
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
                "common_params": cp,
                "client_info": {"client_type": "ide",
                                "device_id": "4333646823299987",
                                "version_code": "20260212",
                                "chat_mode": "code", "icube_language": "zh-CN"},
                "data": d}

    # A: try the second app id
    await post("/api/ide/v2/llm_raw_chat", chat(APP_B), hdrs(jwt, cloudide, APP_B),
               "app id 850edec7")

    # B: add function / config_name
    for fn in ("chat", "builder", "agent", "code", "completion"):
        await post("/api/ide/v2/llm_raw_chat",
                   chat(APP_A, extra_data={"function": fn, "config_name": fn}),
                   hdrs(jwt, cloudide, APP_A), f"function={fn}")

    # C: raw_chat_function (seen in the ModelConfig string block)
    await post("/api/ide/v2/llm_raw_chat",
               chat(APP_A, extra_data={"raw_chat_function": "chat",
                                       "function": "chat"}),
               hdrs(jwt, cloudide, APP_A), "raw_chat_function")

    io.open("logs/_appcfg2.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
