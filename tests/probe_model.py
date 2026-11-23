"""Deliberate experiment: does model_name work with/without Request object?"""
import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.auth import TraeAuth
from trae2api.gateway import TraeGateway


def build_request(g: TraeGateway) -> dict:
    jwt = g.auth.get_jwt()
    c = g.auth.creds
    d = g.auth.device
    return {
        "user_info": {"token": jwt, "is_internal": False, "user_id": c.user_id,
                      "scope": "marscode", "name": c.username, "loginScope": "trae",
                      "tenant_id": "7o2d894p7dr0o4", "email": ""},
        "client_info": {"device_id": d.device_id, "icube_language": "zh-CN",
                        "user_timezone": "Asia/Shanghai", "client_type": "IDE",
                        "window_type": "desktop", "connect_session_id": str(uuid.uuid4())},
        "common_params": {"user_id": c.user_id, "device_id": d.device_id,
                          "machine_id": d.machine_id, "os_name": "Windows",
                          "os_version": "Windows 10 Education", "platform": "electron",
                          "app_version": "3.4.4", "language": "zh-CN", "chat_mode": "DEV",
                          "window_type": "desktop", "region": "CN", "product_code": "TRAE_CN"},
    }


async def probe(g: TraeGateway, label: str, body: dict) -> str:
    try:
        async with g.client.stream("POST", f"{g.base}/api/ide/v1/chat", json=body,
                                   headers=g._headers()) as r:
            first = b""
            try:
                async for chunk in r.aiter_bytes():
                    first += chunk
                    if len(first) > 300:
                        break
            except Exception as e:
                first += str(e).encode()
            head = first.decode("utf-8", "replace")
        if "4023" in head:
            return "UNKNOWN-MODEL"
        if "4001" in head:
            return "BAD-PARAM"
        if "progress_notice" in head or "metadata" in head:
            return "ACCEPTED"
        return f"HTTP{r.status_code}:{head[:60]!r}"
    except Exception as e:
        return f"EXC:{str(e)[:60]}"


async def main() -> None:
    a = TraeAuth()
    a.load()
    g = TraeGateway(a)
    req = build_request(g)

    cases = [
        ("no_model", {}, None),
        ("model+noRequest", {}, "glm-5.3-flash"),
        ("model+Request", {"Request": req}, "glm-5.3-flash"),
        ("model+Request+preset", {"Request": req, "is_preset": True, "provider": ""}, "glm-5.3-flash"),
        ("model+Request+doubao", {"Request": req}, "Doubao-Seed-2.1-Turbo"),
    ]
    for name, extra, model in cases:
        body = {
            "user_input": "hi",
            "session_id": str(uuid.uuid4()),
            "chat_history": [],
        }
        if model is not None:
            body["model_name"] = model
        body.update(extra)
        result = await probe(g, name, body)
        print(f"{name:24} -> {result}", flush=True)
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
