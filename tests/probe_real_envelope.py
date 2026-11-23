"""Test the reconstructed real request envelope against the server.

The decompiled `Request` struct is:
    service, data, user_info, client_info, common_params,
    streamlined_common_params, custom_params, scheduled_task_context
Note: NO `method` - and our earlier probes always sent `method`, which the
Rust side may simply ignore or may be the reason the server treated us as a
different caller class.

Key hypothesis to test: does /api/ide/v1/chat accept the real envelope with
`data` = ChatArgs (61-field shape) and reach a richer path than the flat body?
The flat body works today but yields prompt-injected tools and tool_calls:null.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402
from trae2api import trae_schema  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 240) -> str:
    return " ".join(t.split())[:n]


def events(txt: str) -> list[str]:
    return re.findall(r"^event:\s*(\S+)", txt, re.M)


def sig(txt: str) -> str:
    """Compact signature of the event stream shape."""
    ev = events(txt)
    if not ev:
        return "NO-EVENTS"
    seen = []
    for e in ev:
        if not seen or seen[-1][0] != e:
            seen.append([e, 1])
        else:
            seen[-1][1] += 1
    return " ".join(f"{e}x{c}" for e, c in seen)


def has_structured_tools(txt: str) -> bool:
    for m in re.finditer(r'"tool_calls"\s*:\s*(\[[^\]]*\]|null)', txt):
        if m.group(1) != "null":
            return True
    return False


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = gw._headers()

    text = "Reply with one word: pong"
    sid = str(uuid.uuid4())

    async def post(path, body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== 0. baseline: current flat body (known good) ===")
    flat = {"user_input": text, "session_id": sid, "chat_history": [],
            "message_id": str(uuid.uuid4()),
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder",
                      "title": "Builder"}}
    code, txt = await post("/api/ide/v1/chat", dict(flat))
    log(f"  flat body     -> {code} {sig(txt)}")
    log(f"     structured_tools={has_structured_tools(txt)}")

    # --- the reconstructed real envelope --------------------------------
    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    client_info = {
        "ppe_env_name": "", "connect_session_id": str(uuid.uuid4()),
        "project_id": None, "chat_session_id": sid,
        "version_code": "20260212",
        "workspace_folder": "D:\\workspace\\re_music",
        "icube_language": "zh-CN", "device_id": "4333646823299987",
        "workspace_id": str(uuid.uuid4()), "is_solo_mode": False,
        "client_type": "ide", "window_type": "desktop",
        "git_repos": [], "local_git_repos": [], "git_metadata_dirs": [],
        "security_rules": [], "user_timezone": "Asia/Shanghai",
        "workspace_folders": ["D:\\workspace\\re_music"],
        "authorized_services": [],
    }
    common_params = {"code_window_type": "desktop",
                     "agent_type": "builder",
                     "app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                     "app_version": "3.4.7", "region": "CN"}
    custom_model = {
        "provider": "", "is_preset": True, "config_source": 1,
        "model_name": "deepseek-v4.1-flash",
        "display_model_name": "DeepSeek-V4.1-Flash",
        "use_remote_service": True, "multimodal": True,
        "prompt_max_tokens": 936000, "reasoning_effort_level": "high",
    }
    # ChatArgs subset that plausibly matters
    chat_args = {
        "message_content": [{"type": "text", "text_content": text}],
        "assistant_message_id": "",
        "code_selections": [],
        "workspace_context": {},
        "scene_location": 2,
        "use_file_context": True,
        "use_filepath": True,
        "workspace_folders": ["D:\\workspace\\re_music"],
        "agent_type": "builder",
        "custom_model": custom_model,
        "model_auto_selection": {"strategy": "auto"},
        "is_solo_mode": False,
        "is_in_plan_mode": False,
        "is_in_spec_mode": False,
        "is_in_code_mode": False,
        "origin": "ide",
        "turn_id": str(uuid.uuid4()),
    }

    envelope = {
        "service": "chat",
        "data": chat_args,
        "user_info": u,
        "client_info": client_info,
        "common_params": common_params,
        "streamlined_common_params": common_params,
    }

    log("\n=== 1. real envelope (Request schema, no `method`) ===")
    code, txt = await post("/api/ide/v1/chat", dict(envelope))
    log(f"  envelope      -> {code} {sig(txt)}")
    log(f"     structured_tools={has_structured_tools(txt)}")
    log(f"     {brief(txt, 300)}")

    log("\n=== 2. same envelope + method (our old habit) ===")
    code, txt = await post("/api/ide/v1/chat",
                           dict(envelope, method="chat"))
    log(f"  +method       -> {code} {sig(txt)}")
    log(f"     structured_tools={has_structured_tools(txt)}")

    log("\n=== 3. envelope on the raw_chat endpoints ===")
    for p in ("/api/ide/v2/llm_raw_chat", "/api/ide/v1/llm_raw_chat"):
        code, txt = await post(p, dict(envelope))
        log(f"  {p:30} -> {code} {brief(txt, 170)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_realenvelope.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
