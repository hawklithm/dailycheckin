"""Use the leaked config-lookup key to make create_agent_task succeed.

create_agent_task now returns 200 + SSE and fails only on server-side config:

    config item is empty for config opt: {
      "AppId":"6eefa01c-...", "Function":"solo_agent",
      "ConfigName":"deepseek-v4.1-flash", "VersionCode":20260212,
      "ModeType":0, "AgentType":"solo_agent", "IsCustomModel":false,
      "Account":{...}, "Provider":"", "RequireMultimodel":false }

This is the exact tuple we never knew for the original
"2001 failed to get app config" error. Now that we can see it, we can vary the
parts we control - Function, ConfigName, ModeType, AgentType - and look for a
tuple the server DOES have config for.

Sources for candidate values:
  * chat_mode endpoint earlier reported mode_type:1, trae_request_type:0
  * renderer logs showed agent_type solo_agent + config_name deepseek-v4.1-flash
  * ModelHandler methods include model_list_by_function / prefetch_for_auto
  * ApplicationConfig had enable_agent_process_v3 etc.
"""
from __future__ import annotations

import asyncio
import io
import itertools
import json
import os
import re
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


def brief(t: str, n: int = 300) -> str:
    return " ".join(t.split())[:n]


def legacy(jwt, region):
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
        "Accept": "text/event-stream",
    }


def classify(txt: str) -> str:
    if "config item is empty" in txt:
        return "CONFIG-EMPTY"
    if "missing required parameter" in txt:
        m = re.search(r"expr_path=([\w\.]+)", txt)
        return f"NEED:{m.group(1) if m else '?'}"
    if "output" in txt or "token_usage" in txt:
        return "STREAM!"
    if "error" in txt:
        m = re.search(r'"message":"([^"]{0,60})', txt)
        return f"ERR:{m.group(1) if m else '?'}"
    return "other"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)
    url = f"{gw.base}/api/agent/v3/create_agent_task"

    sid = str(uuid.uuid4())
    text = "hi"

    def payload(fn, cfg, mode, atype):
        return {
            "conversation_id": sid, "session_id": sid,
            "user_id": auth.creds.user_id,
            "device_id": "4333646823299987",
            "agent_type": atype, "model_name": cfg, "config_name": cfg,
            "ide_version": "1.107.1",
            "mode_type": mode,
            "user_input": {"id": str(uuid.uuid4()), "text": text},
        }

    async def post(body, timeout=45):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== sweep Function x ConfigName x ModeType x AgentType ===")
    functions = ["solo_agent", "builder", "chat", "agent", "code"]
    configs = ["deepseek-v4.1-flash", "auto", "deepseek-v4-flash"]
    modes = [0, 1]
    atypes = ["solo_agent", "builder", "chat"]

    results = {}
    seen_combos = 0
    for fn, cfg, mode, at in itertools.product(functions, configs, modes,
                                               atypes):
        code, txt = await post(payload(fn, cfg, mode, at))
        cls = classify(txt)
        seen_combos += 1
        results[cls] = results.get(cls, 0) + 1
        if cls not in ("CONFIG-EMPTY",):
            log(f"  fn={fn:12} cfg={cfg:22} mode={mode} at={at:11} "
                f"-> {code} {cls}   {brief(txt, 150)}")
        if seen_combos % 20 == 0:
            log(f"    ... {seen_combos} combos, summary {results}")

    log(f"\n=== summary over {seen_combos} combos ===")
    for k, v in sorted(results.items(), key=lambda kv: -kv[1]):
        log(f"    {k:24} x{v}")

    log("\n=== control: does a bad config name change the error text? ===")
    code, txt = await post(payload("solo_agent", "definitely-not-a-model", 0,
                                   "solo_agent"))
    log(f"  -> {code} {classify(txt)}")
    log(f"     {brief(txt, 400)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_cfgsweep.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
