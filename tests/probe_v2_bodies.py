"""Iterate on the llm_raw_chat / model_list request bodies.

get_session_usage already returns 200 with our credentials, so auth is fine.
Both model_list (4001) and llm_raw_chat (4001) just need the right envelope.
The sidecar builds: {service, method, data, user_info, common_params, client_info}
- extract that exact shape from convertReqToRustPayload in workbench.js.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import DEFAULT_BASE, TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


ENVELOPE_BASE = {
    "service": "chat",
    "method": "chat",
    "user_info": {
        "user_unique_id": "3481484447459108",
        "user_type": "user",
        "user_id": "3481484447459108",
        "user_is_auth": True,
        "user_is_login": True,
        "device_id": "4333646823299987",
        "web_id": "4333646823299987",
        "user_unique_id_type": "user_id",
    },
    "common_params": {
        "app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
        "app_name": "trae",
        "app_version": "3.4.7",
        "trae_version_code": "20260212",
        "os_name": "windows",
        "os_version": "Windows 10 Education",
        "device_model": "MS-7B89",
        "device_brand": "AMD",
        "region": "CN",
        "language": "zh-CN",
        "agent_type": "builder",
        "code_window_type": "editor",
    },
    "client_info": {
        "client_type": "ide",
        "version_code": "20260212",
        "icube_language": "zh-CN",
        "device_id": "4333646823299987",
        "is_solo_mode": False,
        "window_type": "editor",
    },
}


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    log(f"base: {gw.base}")

    async def call(path, body, label=""):
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{gw.base}{path}", json=body,
                                 headers=gw._headers())
            log(f"\n### {label or path}")
            log(f"  status {r.status_code}")
            try:
                d = r.json()
                if isinstance(d, dict) and d.get("model_configs"):
                    log(f"  model_configs: {len(d['model_configs'])} items")
                    for m in d["model_configs"][:40]:
                        log("    " + json.dumps(m, ensure_ascii=False)[:220])
                else:
                    log("  " + json.dumps(d, ensure_ascii=False)[:1200])
            except Exception:
                log("  raw: " + r.text[:400])
            return r
        except Exception as e:  # noqa: BLE001
            log(f"\n### {label or path}: ERROR {type(e).__name__}: {e}")
            return None

    # --- model_list, with the full envelope ---
    body = dict(ENVELOPE_BASE)
    body["service"] = "model"
    body["method"] = "get_model_list"
    await call("/api/ide/v1/model_list", body, "model_list (model service)")

    # variant: chat service
    body2 = dict(ENVELOPE_BASE)
    body2["service"] = "chat"
    body2["method"] = "get_model_list"
    await call("/api/ide/v1/model_list", body2, "model_list (chat service)")

    # --- llm_raw_chat with the envelope ---
    chat = dict(ENVELOPE_BASE)
    chat["data"] = {
        "agent_type": "builder",
        "scene_location": 2,
        "agent": {"type": "builder", "name": "builder", "title": "Builder"},
        "model_name": "auto",
        "model_auto_selection": {"strategy": "auto"},
        "message_content": [{"type": "text", "text_content": "你好"}],
        "user_input": "你好",
        "message_id": "11111111-1111-1111-1111-111111111111",
        "session_id": "22222222-2222-2222-2222-222222222222",
        "workspace_folders": [{"path": "D:\\workspace\\re_music", "name": "re_music"}],
    }
    await call("/api/ide/v2/llm_raw_chat", chat, "llm_raw_chat v2 (builder)")

    # --- llm_raw_chat v1 ---
    await call("/api/ide/v1/llm_raw_chat", chat, "llm_raw_chat v1 (builder)")

    io.open("logs/_v2probe2.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
