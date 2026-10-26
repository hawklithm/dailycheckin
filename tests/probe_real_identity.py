"""Try the ground-truth values recovered from Trae's own renderer logs.

Proven from logs\\_realmodelinfo.txt (live 3.4.7 session):
  config_name / model_name : "deepseek-v4.1-flash"
  model.display_model_name : "DeepSeek-V4.1-Flash"
  agent_type               : "solo_agent"
  reasoning_effort_level   : "high"
  is_preset true, config_source 1, multimodal true, prompt_max_tokens 936000

Previously every probe guessed these. Now we try the real ones, and vary
which layer / field carries them, until batch_get_detail_param returns a
non-empty function_configs or llm_raw_chat stops returning 2001.
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

CONFIG_NAME = "deepseek-v4.1-flash"
AGENT_TYPE = "solo_agent"


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


def nonempty(text: str) -> bool:
    try:
        return bool(json.loads(text).get("function_configs"))
    except Exception:  # noqa: BLE001
        return False


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

    async def post(path, body, timeout=60):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== A. batch_get_detail_param with real config_name ===")
    variants = [
        ("functions=[config_name]",
         {"service": "model", "method": "batch_get_detail_param",
          "user_info": dict(u), "common_params": dict(cp),
          "client_info": dict(ci),
          "data": {"functions": [CONFIG_NAME]}}),
        ("functions=[agent_type]",
         {"service": "model", "method": "batch_get_detail_param",
          "user_info": dict(u), "common_params": dict(cp),
          "client_info": dict(ci),
          "data": {"functions": [AGENT_TYPE]}}),
        ("+agent_type in common_params",
         {"service": "model", "method": "batch_get_detail_param",
          "user_info": dict(u),
          "common_params": {**cp, "agent_type": AGENT_TYPE},
          "client_info": dict(ci),
          "data": {"functions": [CONFIG_NAME]}}),
        ("model_names=[config_name]",
         {"service": "model", "method": "batch_get_detail_param",
          "user_info": dict(u), "common_params": dict(cp),
          "client_info": dict(ci),
          "data": {"model_names": [CONFIG_NAME]}}),
    ]
    for label, body in variants:
        code, txt = await post("/api/ide/v1/batch_get_detail_param", body)
        mark = "   <== NON-EMPTY" if nonempty(txt) else ""
        log(f"  {label:30} -> {code} {txt[:220]}{mark}")

    log("\n=== B. get_detail_param with real model_name ===")
    body = {"service": "model", "method": "get_detail_param",
            "user_info": dict(u), "common_params": dict(cp),
            "client_info": dict(ci),
            "data": {"model_name": CONFIG_NAME}}
    code, txt = await post("/api/ide/v1/get_detail_param", body)
    log(f"  get_detail_param -> {code} {txt[:400]}")

    log("\n=== C. model_list with real identity ===")
    body = {"service": "model", "method": "model_list",
            "user_info": dict(u),
            "common_params": {**cp, "agent_type": AGENT_TYPE},
            "client_info": {**ci, "agent_type": AGENT_TYPE},
            "data": {"agent_type": AGENT_TYPE}}
    code, txt = await post("/api/ide/v1/model_list", body)
    log(f"  model_list -> {code} {txt[:400]}")

    log("\n=== D. llm_raw_chat with real model_info ===")
    model_info = {
        "provider": "", "is_preset": True, "config_source": 1,
        "config_name": CONFIG_NAME, "model_name": CONFIG_NAME,
        "display_model_name": "DeepSeek-V4.1-Flash",
        "use_remote_service": True, "multimodal": True,
        "prompt_max_tokens": 936000, "reasoning_effort_level": "high",
    }
    base_data = {
        "user_input": "hi",
        "message_content": [{"type": "text", "text_content": "hi"}],
        "agent_type": AGENT_TYPE,
        "agent": {"type": AGENT_TYPE, "name": AGENT_TYPE, "title": "SOLO Agent"},
        "model_name": CONFIG_NAME,
        "config_name": CONFIG_NAME,
        "scene_location": 2,
        "session_id": str(uuid.uuid4()),
        "message_id": str(uuid.uuid4()),
        "workspace_folders": [{"path": "D:\\workspace\\re_music",
                               "name": "re_music"}],
    }
    raw = [
        ("model_name+config_name", {}),
        ("+model_info object", {"model_info": model_info}),
        ("+custom_model", {"custom_model": model_info}),
        ("+reasoning_effort_level",
         {"reasoning_effort_level": "high"}),
        ("+function=<config_name>",
         {"function": CONFIG_NAME, "raw_chat_function": CONFIG_NAME}),
    ]
    for label, extra in raw:
        data = {**base_data, **extra}
        body = {"service": "chat", "method": "chat", "user_info": dict(u),
                "common_params": {**cp, "agent_type": AGENT_TYPE},
                "client_info": {**ci, "agent_type": AGENT_TYPE},
                "data": data}
        code, txt = await post("/api/ide/v2/llm_raw_chat", body, timeout=90)
        good = "record not found" not in txt
        log(f"  {label:26} -> {code} {txt[:240]}"
            + ("   <== PROGRESSED" if good else ""))

    io.open("logs/_realidentity.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
