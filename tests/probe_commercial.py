"""Call the real commercial endpoints (api/v1/commercial/*, not /api/ide/v1/*).

The DLL string is api/v1/commercial/get_mode_info - our earlier probe used the
wrong prefix (/api/ide/v1/commercial/...) and got 404. These may return the app
config the llm_raw_chat 2001 error says is missing.
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
            log(f"\n[{label}] {path} -> {r.status_code}")
            log("   " + r.text[:900])
            return r
        except Exception as e:  # noqa: BLE001
            log(f"\n[{label}] {path} -> ERR {type(e).__name__}: {e}")
            return None

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    cp = {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_version": "3.4.7", "region": "CN", "package_type": "stable_cn"}
    ci = {"client_type": "ide", "device_id": "4333646823299987",
          "version_code": "20260212", "chat_mode": "code"}

    for method in ("get_mode_info", "chat_mode", "save_status"):
        await post(f"/api/v1/commercial/{method}",
                   {"service": "commercial", "method": method,
                    "user_info": u, "common_params": cp, "client_info": ci},
                   method)

    # get_session_usage with the same envelope (it worked before)
    await post("/api/v1/commercial/get_session_usage",
               {"service": "commercial", "method": "get_session_usage",
                "user_info": u, "common_params": cp, "client_info": ci,
                "data": {"session_id": str(uuid.uuid4())}},
               "get_session_usage")

    io.open("logs/_comm2.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
