"""Re-test the config endpoints with the header set the real client uses.

Evidence: Trae's own completion.log logs the exact headers it sends for
api/ide/v1/get_detail_param, and they are the LEGACY device set, not the
"modern" one:

    {"X-App-Id":"6eefa01c-...","x-plugin-channel":"icube-ai",
     "x-ide-version-code":"20260212","x-ide-token":"******",
     "Content-Type":"application/json","Authorization":"Cloud-IDE-JWT ******",
     "X-Device-Cpu":"AMD","X-Device-Id":"4333646823299987",
     "X-Machine-Id":"56cb66...","X-Device-Brand":"MS-7B89",
     "X-Device-Type":"windows","X-Os-Version":"Windows%2010%20Education"}

The client gets 200 from get_detail_param with those; our "modern" headers
return 500. So the modern-vs-legacy rule from the handoff only applies to
v2/llm_raw_chat, not to the config endpoints. Try both sets on each endpoint.
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


def modern(jwt, cloudide):
    trace = uuid.uuid4().hex[:16]
    return {
        "Authorization": f"Cloud-IDE-JWT {jwt}",
        "x-cloudide-token": cloudide,
        "content-type": "application/json",
        "accept": "*/*",
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


def legacy(jwt, region):
    """Byte-for-byte the header set the real client logged."""
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


def brief(t: str, n: int = 300) -> str:
    return " ".join(t.split())[:n]


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    jwt = auth.get_jwt()
    MOD = modern(jwt, auth.creds.token)
    LEG = legacy(jwt, auth.creds.region)

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    cp = {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_name": "trae", "region": "CN", "app_version": "3.4.7",
          "package_type": "stable_cn"}
    ci = {"client_type": "ide", "device_id": "4333646823299987",
          "version_code": "20260212", "chat_mode": "code"}

    async def post(path, body, headers, timeout=45):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=headers)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    paths = ["/api/ide/v1/get_detail_param",
             "/api/ide/v1/get_client_config",
             "/api/ide/v1/batch_get_detail_param",
             "/api/ide/v1/model_list",
             "/api/ide/v1/code_completion/model_configs"]
    bodies = [
        ("empty {}", {}),
        ("full envelope", {"service": "model", "method": "get_detail_param",
                           "user_info": dict(u), "common_params": dict(cp),
                           "client_info": dict(ci),
                           "data": {"model_name": "deepseek-v4.1-flash"}}),
    ]

    log("=== legacy vs modern headers per endpoint ===")
    for p in paths:
        for bname, body in bodies:
            for hname, H in (("modern", MOD), ("legacy", LEG)):
                code, txt = await post(p, body, H)
                ok = code == 200 and '"code":0' not in txt
                good = code == 200
                line = f"  {p:44} {bname:14} {hname:7} -> {code}"
                if good:
                    line += " OK  " + brief(txt, 180)
                else:
                    line += "     " + brief(txt, 90)
                log(line)
                if good and ok:
                    pass
        log("")

    log("=== llm_raw_chat: legacy headers? (handoff says this 4001s) ===")
    data = {"user_input": "hi",
            "message_content": [{"type": "text", "text_content": "hi"}],
            "model_name": "deepseek-v4.1-flash",
            "config_name": "deepseek-v4.1-flash",
            "agent_type": "solo_agent",
            "session_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4())}
    body = {"service": "chat", "method": "chat", "user_info": dict(u),
            "common_params": {**cp, "agent_type": "solo_agent"},
            "client_info": dict(ci), "data": data}
    for hname, H in (("modern", MOD), ("legacy", LEG)):
        code, txt = await post("/api/ide/v2/llm_raw_chat", body, H, timeout=90)
        good = "record not found" not in txt
        log(f"  {hname:7} -> {code} {brief(txt, 200)}"
            + ("   <== PROGRESSED" if good else ""))

    io.open("logs/_hdrmatrix.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
