"""Test app id B: 850edec7-b9d0-48aa-99b5-67c888e282cd.

The handoff lists two app ids and says B was never tried. Every probe so far
pinned A (6eefa01c-...). Entitlement data shows every pack with
available_endpoint: 0, and different app ids plausibly land in different
quota / risk-control buckets, so this is the cheapest remaining lever.

app id appears in two places - the X-App-Id header and common_params.app_id -
so both are switched together, and each is switched alone to see which one
the server actually reads.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import uuid
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []

IDA = "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"
IDB = "850edec7-b9d0-48aa-99b5-67c888e282cd"


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def legacy(jwt, region, app_id):
    return {
        "X-App-Id": app_id,
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
        "Accept": "text/event-stream",
    }


def brief(t: str, n: int = 200) -> str:
    return " ".join(t.split())[:n]


def verdict(txt: str) -> str:
    for k in ("2001", "4011", "4001", "4023"):
        if k in txt:
            return k
    if "token_usage" in txt or '"response"' in txt:
        return "STREAM!"
    return "other"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    jwt = auth.get_jwt()

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    ci = {"client_type": "ide", "device_id": "4333646823299987",
          "version_code": "20260212", "chat_mode": "code"}

    def cp(app_id):
        return {"app_id": app_id, "app_name": "trae", "region": "CN",
                "app_version": "3.4.7", "package_type": "stable_cn"}

    data = {"user_input": "hi",
            "message_content": [{"type": "text", "text_content": "hi"}],
            "model_name": "deepseek-v4.1-flash",
            "config_name": "deepseek-v4.1-flash",
            "agent_type": "solo_agent", "scene_location": 2,
            "session_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "workspace_folders": [{"path": "D:\\workspace\\re_music",
                                   "name": "re_music"}]}

    async def post(path, body, headers, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body,
                                 headers=headers)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== A/B: which app id does the server honour? ===")
    combos = [
        ("hdr=A body=A (baseline)", IDA, IDA),
        ("hdr=B body=B", IDB, IDB),
        ("hdr=B body=A", IDB, IDA),
        ("hdr=A body=B", IDA, IDB),
    ]
    for label, hid, bid in combos:
        H = legacy(jwt, auth.creds.region, hid)
        body = {"service": "chat", "method": "chat", "user_info": dict(u),
                "common_params": {**cp(bid), "agent_type": "solo_agent"},
                "client_info": dict(ci), "data": dict(data)}
        code, txt = await post("/api/ide/v2/llm_raw_chat", body, H)
        v = verdict(txt)
        flag = "   <== CHANGED" if v != "4011" else ""
        log(f"  {label:26} -> {code} [{v}] {brief(txt, 150)}{flag}")

    log("\n=== app id B across other endpoints ===")
    HB = legacy(jwt, auth.creds.region, IDB)
    for path, meth, extra in [
            ("/api/ide/v1/get_detail_param", "get_detail_param",
             {"model_name": "deepseek-v4.1-flash"}),
            ("/api/ide/v1/batch_get_detail_param", "batch_get_detail_param",
             {"functions": ["chat"]}),
            ("/api/ide/v1/model_list", "model_list", {}),
            ("/api/ide/v1/ping", "ping", {}),
            ("/api/ide/v1/get_client_config", "get_client_config", {})]:
        body = {"service": "model", "method": meth, "user_info": dict(u),
                "common_params": cp(IDB), "client_info": dict(ci),
                "data": extra}
        code, txt = await post(path, body, HB)
        log(f"  {path:44} -> {code} {brief(txt, 170)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_appidb.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
