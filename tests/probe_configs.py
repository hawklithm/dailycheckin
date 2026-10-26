"""Probe the config-provider endpoints.

llm_raw_chat answers 2001 "failed to get app config: record not found" even
though get_session_usage and chat_mode both return 200 with the same envelope.
So a *record* has to exist. Candidates visible in the endpoint list:
  /api/ide/v1/get_custom_model_type_config
  /api/ide/v1/get_detail_param
  /api/ide/v1/batch_get_detail_param
  /api/ide/v1/providers
and the LLMAdapter logs show update_model / connect_model run before chat, so
one of those may create the missing record.
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
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            txt = r.text[:700]
            log(f"\n[{label}] {path} -> {r.status_code}")
            log("   " + txt)
            if '"code"' in txt and '"code":0' in txt.replace(" ", ""):
                log("   *** code 0 ***")
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

    def env(svc, meth, data=None):
        return {"service": svc, "method": meth, "user_info": u,
                "common_params": cp, "client_info": ci,
                "data": data or {}}

    # sanity + config providers
    await post("/api/ide/v1/ping", env("system", "ping"), "ping")
    await post("/api/ide/v1/get_custom_model_type_config",
               env("model", "get_custom_model_type_config"), "custom_model_type_config")
    await post("/api/ide/v1/get_detail_param",
               env("model", "get_detail_param", {"model_name": "auto"}),
               "get_detail_param")
    await post("/api/ide/v1/batch_get_detail_param",
               env("model", "batch_get_detail_param",
                   {"model_names": ["auto"]}), "batch_get_detail_param")
    await post("/api/ide/v1/providers", env("model", "providers"), "providers")

    io.open("logs/_cfgprobe.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
