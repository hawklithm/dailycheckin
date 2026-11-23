"""Probe get_client_config - the endpoint behind 'failed to get app config'.

The Trae client's own ApiManager log shows three paths actually resolved
against trae-api-cn.mchost.guru, thousands of times:
    api/ide/v1/get_detail_param          x520
    api/ide/v1/code_completion/model_configs  x260
    api/ide/v1/get_client_config         x256   <-- never probed by us

`llm_raw_chat` fails with "failed to get app config: record not found", which
reads exactly like a client-config lookup miss. So: figure out what makes
get_client_config return data, then retry llm_raw_chat.
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


def brief(t: str, n: int = 420) -> str:
    return " ".join(t.split())[:n]


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = hdrs(auth.get_jwt(), auth.creds.token)

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    cp = {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_name": "trae", "region": "CN", "app_version": "3.4.7",
          "package_type": "stable_cn"}
    ci = {"client_type": "ide", "device_id": "4333646823299987",
          "version_code": "20260212", "chat_mode": "code"}

    async def post(path, body, timeout=45):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    def envelope(svc, meth, data=None):
        return {"service": svc, "method": meth, "user_info": dict(u),
                "common_params": dict(cp), "client_info": dict(ci),
                "data": data or {}}

    log("=== get_client_config: shape hunt ===")
    trials = [
        ("empty data", envelope("config", "get_client_config")),
        ("service=configuration", envelope("configuration",
                                           "get_client_config")),
        ("service=ide", envelope("ide", "get_client_config")),
        ("bare {}", {}),
        ("only user_info", {"user_info": dict(u)}),
        ("+scene/version", envelope("config", "get_client_config",
                                    {"scene": "chat", "version": "0"})),
        ("+client_type", envelope("config", "get_client_config",
                                  {"client_type": "ide"})),
    ]
    for label, body in trials:
        code, txt = await post("/api/ide/v1/get_client_config", body)
        log(f"  {label:22} -> {code} {brief(txt, 300)}")

    log("\n=== code_completion/model_configs (known-good control) ===")
    code, txt = await post("/api/ide/v1/code_completion/model_configs",
                           {"common_params": dict(cp)})
    log(f"  -> {code} {brief(txt, 300)}")

    log("\n=== does get_client_config change llm_raw_chat? ===")
    cfgpairs = [
        ("none", None),
        ("config/get_client_config", envelope("config", "get_client_config")),
    ]
    for label, cfg in cfgpairs:
        if cfg is not None:
            await post("/api/ide/v1/get_client_config", cfg)
        data = {"user_input": "hi",
                "message_content": [{"type": "text", "text_content": "hi"}],
                "model_name": "deepseek-v4.1-flash",
                "config_name": "deepseek-v4.1-flash",
                "agent_type": "solo_agent",
                "agent": {"type": "solo_agent", "name": "solo_agent",
                          "title": "SOLO Agent"},
                "scene_location": 2,
                "session_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4())}
        body = {"service": "chat", "method": "chat", "user_info": dict(u),
                "common_params": {**cp, "agent_type": "solo_agent"},
                "client_info": dict(ci), "data": data}
        code, txt = await post("/api/ide/v2/llm_raw_chat", body, timeout=90)
        good = "record not found" not in txt
        log(f"  after[{label:26}] -> {code} {brief(txt, 260)}"
            + ("   <== PROGRESSED" if good else ""))

    io.open("logs/_clientconfig.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
