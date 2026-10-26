"""Find the 'function' key that unlocks the model config.

The sidecar caches model config by (user_id, env, function):
  INSERT INTO model_config_cache (user_id, env, function, config_data)
  "Retrieved model config cache for user: ?, env: ?, function: ?, configs count: ?"
Our batch_get_detail_param came back with function_configs: [] - no record for
the function we (implicitly) asked for. Enumerate candidates until one returns
a non-empty config, then feed that function into llm_raw_chat.
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

FUNCTIONS = [
    "chat", "builder", "agent", "code", "completion", "solo", "plan",
    "edit", "inline_chat", "reader", "custom", "assistant",
    "chat_builder", "agent_builder", "solo_builder", "solo_coding",
    "fast_apply", "commit_message", "summary", "terminal",
]


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

    async def batch(function):
        body = {"service": "model", "method": "batch_get_detail_param",
                "user_info": u, "common_params": cp, "client_info": ci,
                "data": {"functions": [function]}}
        try:
            async with httpx.AsyncClient(timeout=45) as c:
                r = await c.post(
                    f"{gw.base}/api/ide/v1/batch_get_detail_param",
                    json=body, headers=H)
            t = r.text
            n = t.count('"function_configs":[]')
            ok = '"function_configs":[]' not in t.replace(" ", "")
            return r.status_code, ok, t[:260]
        except Exception as e:  # noqa: BLE001
            return 0, False, f"ERR {e}"

    log("=== which 'function' returns a non-empty config? ===")
    found = []
    for fn in FUNCTIONS:
        code, ok, txt = await batch(fn)
        mark = "  <== NON-EMPTY" if ok else ""
        log(f"  {fn:16} {code} {txt[:150]}{mark}")
        if ok:
            found.append(fn)

    log(f"\nnon-empty functions: {found}")

    # feed the winners into llm_raw_chat
    for fn in (found or ["chat"])[:4]:
        body = {
            "service": "chat", "method": "chat",
            "user_info": u,
            "common_params": {**cp, "agent_type": "builder"},
            "client_info": ci,
            "data": {
                "user_input": "hi",
                "message_content": [{"type": "text", "text_content": "hi"}],
                "model_name": "auto",
                "function": fn,
                "raw_chat_function": fn,
                "agent_type": "builder", "scene_location": 2,
                "agent": {"type": "builder", "name": "builder",
                          "title": "Builder"},
                "session_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()),
                "workspace_folders": [{"path": "D:\\workspace\\re_music",
                                       "name": "re_music"}],
            },
        }
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{gw.base}/api/ide/v2/llm_raw_chat",
                                 json=body, headers=H)
            log(f"\n[llm_raw_chat function={fn}] -> {r.status_code} "
                f"{r.text[:260]}")
        except Exception as e:  # noqa: BLE001
            log(f"\n[llm_raw_chat function={fn}] -> ERR {e}")

    io.open("logs/_funcenum.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
