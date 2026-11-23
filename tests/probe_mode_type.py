"""mode_type / trae_request_type: the last untested knob.

commercial/chat_mode returns:
    {"mode_list":[{"default_status":true,"mode_type":1,
                   "trae_request_type":1, "upgrade...":...}]}

Earlier notes recorded mode_type 1 / trae_request_type 0, now it is 1/1.
These are exactly the values that go into the config lookup key the server
leaked earlier:

    {"AppId":..., "Function":"solo_agent", "ConfigName":"deepseek-v4.1-flash",
     "VersionCode":20260212, "ModeType":0, "AgentType":"solo_agent", ...}

Note ModeType was 0 in that dump while chat_mode advertises mode_type 1.
So try ModeType=1 (and trae_request_type) in the agent/v3 calls - the config
key would then match what the account actually has provisioned.

Also fetch the full chat_mode payload to see every field the server expects us
to send.
"""
from __future__ import annotations

import asyncio
import io
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


def brief(t: str, n: int = 400) -> str:
    return " ".join(t.split())[:n]


def kind(txt: str) -> str:
    if "exceeded the rate limit" in txt:
        return "4011"
    if "no function config found" in txt:
        return "no-config"
    if "config item is empty" in txt:
        return "config-empty"
    if "token_usage" in txt:
        return "STREAM OK"
    m = re.search(r'"message":"([^"]{0,60})', txt)
    return (m.group(1)[:50] if m else "other")


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


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)

    async def post(path, body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== A. full chat_mode payload ===")
    code, txt = await post("/api/v1/commercial/chat_mode", {})
    log(f"  -> {code}")
    try:
        j = json.loads(txt)
        log(json.dumps(j, indent=2, ensure_ascii=False)[:2500])
    except Exception:  # noqa: BLE001
        log("  " + brief(txt, 800))

    log("\n=== B. agent/v3 llm_utils_chat with mode_type / trae_request_type ===")
    text = "Reply with one word: pong"

    def p(**extra):
        sid = str(uuid.uuid4())
        b = {"user_input": text, "conversation_id": sid, "session_id": sid,
             "user_id": auth.creds.user_id,
             "device_id": "4333646823299987", "ide_version": "1.107.1",
             "function": "solo_agent"}
        b.update(extra)
        return b

    trials = {
        "baseline": {},
        "mode_type=1": {"mode_type": 1},
        "mode_type=0": {"mode_type": 0},
        "trae_request_type=0": {"trae_request_type": 0},
        "trae_request_type=1": {"trae_request_type": 1},
        "mode=1 trt=1": {"mode_type": 1, "trae_request_type": 1},
        "mode=1 trt=0": {"mode_type": 1, "trae_request_type": 0},
        "mode=0 trt=1": {"mode_type": 0, "trae_request_type": 1},
        "mode=0 trt=0": {"mode_type": 0, "trae_request_type": 0},
    }
    for label, extra in trials.items():
        code, txt = await post("/api/agent/v3/llm_utils_chat", p(**extra))
        log(f"  {label:22} -> {code} {kind(txt)}")

    log("\n=== C. create_agent_task with mode_type=1 ===")
    def ct(mode):
        sid = str(uuid.uuid4())
        return {"conversation_id": sid, "session_id": sid,
                "user_id": auth.creds.user_id,
                "device_id": "4333646823299987",
                "agent_type": "solo_agent",
                "model_name": "deepseek-v4.1-flash",
                "config_name": "deepseek-v4.1-flash",
                "ide_version": "1.107.1", "mode_type": mode,
                "user_input": {"id": str(uuid.uuid4()), "text": text}}

    for mode in (0, 1):
        code, txt = await post("/api/agent/v3/create_agent_task", ct(mode))
        log(f"  mode_type={mode} -> {code} {kind(txt)}")
        if kind(txt) not in ("config-empty",):
            log(f"      {brief(txt, 300)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_modetype.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
