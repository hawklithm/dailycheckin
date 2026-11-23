"""Test the `env` dimension of the model config cache key.

The sidecar caches model config by (user_id, env, function):
  INSERT INTO model_config_cache (user_id, env, function, config_data, ...)
  "Retrieved model config cache for user: ~~, env: ~~, function: ~~, configs count: ~~"
and a dll string dump shows the literal value `prod` right next to the
"Saved model config cache batch" message - so `prod` is a real env value.

Every probe so far varied only `function` (and got function_configs: [] for
all 20 candidates). Nobody has ever sent an `env` field. This probe varies
env x placement x function until batch_get_detail_param returns a non-empty
function_configs, then feeds the winner into llm_raw_chat.
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


def nonempty(text: str) -> bool:
    try:
        j = json.loads(text)
    except Exception:  # noqa: BLE001
        return False
    fc = j.get("function_configs")
    return bool(fc)


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

    ENVS = ["prod", "production", "online", "cn", "desktop", "ide",
            "stable_cn", "default", "ppe", "boe"]
    PLACEMENTS = ["common_params", "top", "data", "user_info", "client_info"]
    FUNCTIONS = ["chat", "builder", "agent"]

    async def batch(env, where, fn):
        body = {"service": "model", "method": "batch_get_detail_param",
                "user_info": dict(u), "common_params": dict(cp),
                "client_info": dict(ci), "data": {"functions": [fn]}}
        if where == "common_params":
            body["common_params"]["env"] = env
        elif where == "top":
            body["env"] = env
        elif where == "data":
            body["data"]["env"] = env
        elif where == "user_info":
            body["user_info"]["env"] = env
        elif where == "client_info":
            body["client_info"]["env"] = env
        try:
            async with httpx.AsyncClient(timeout=45) as c:
                r = await c.post(
                    f"{gw.base}/api/ide/v1/batch_get_detail_param",
                    json=body, headers=H)
            return r.status_code, nonempty(r.text), r.text[:300]
        except Exception as e:  # noqa: BLE001
            return 0, False, f"ERR {e}"

    log("=== phase 1: env x placement (function=chat) ===")
    winners = []
    for where in PLACEMENTS:
        for env in ENVS:
            code, ok, txt = await batch(env, where, "chat")
            if code != 200 or ok:
                log(f"  [{where:14}] env={env:12} -> {code} {txt[:170]}"
                    + ("   <== NON-EMPTY" if ok else ""))
            if ok:
                winners.append((env, where))
    if not any(w[0] for w in winners):
        log("  (all empty - env axis alone does not unlock it)")

    log("\n=== phase 2: env x function (best placements) ===")
    found = []
    for env, where in (winners or [(e, p) for e in ENVS[:3]
                                   for p in PLACEMENTS[:2]]):
        for fn in FUNCTIONS:
            code, ok, txt = await batch(env, where, fn)
            log(f"  env={env:10} [{where:14}] fn={fn:10} -> {code} {txt[:150]}"
                + ("   <== NON-EMPTY" if ok else ""))
            if ok:
                found.append((env, where, fn))

    log("\n=== phase 3: llm_raw_chat with the discovered env ===")
    trials = found or [("prod", "common_params", "chat")]
    for env, where, fn in trials[:6]:
        body = {"service": "chat", "method": "chat",
                "user_info": dict(u),
                "common_params": {**cp, "agent_type": "builder"},
                "client_info": dict(ci),
                "data": {"user_input": "hi",
                         "message_content": [{"type": "text",
                                              "text_content": "hi"}],
                         "model_name": "auto", "function": fn,
                         "raw_chat_function": fn,
                         "agent_type": "builder", "scene_location": 2,
                         "agent": {"type": "builder", "name": "builder",
                                   "title": "Builder"},
                         "session_id": str(uuid.uuid4()),
                         "message_id": str(uuid.uuid4()),
                         "workspace_folders": [
                             {"path": "D:\\workspace\\re_music",
                              "name": "re_music"}]}}
        if where == "common_params":
            body["common_params"]["env"] = env
        elif where == "top":
            body["env"] = env
        elif where == "data":
            body["data"]["env"] = env
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{gw.base}/api/ide/v2/llm_raw_chat",
                                 json=body, headers=H)
            log(f"\n  [raw_chat env={env} {where} fn={fn}] -> {r.status_code}"
                f" {r.text[:300]}")
        except Exception as e:  # noqa: BLE001
            log(f"\n  [raw_chat env={env}] -> ERR {e}")

    io.open("logs/_envaxis.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
