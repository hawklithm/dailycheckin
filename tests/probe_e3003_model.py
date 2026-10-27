"""3003 = "all models failed": the envelope is accepted, model selection fails.

That is a big step forward. With the decompiled `Request` envelope the server
now:
    progress_notice -> prompt -> error 3003 "all models failed" -> done
i.e. it built the prompt and then failed to dispatch to a model. Earlier
errors (2001/4011/4001) never got this far.

So the remaining unknown is narrow: what does the server need to pick a model?
Candidates, from the decompiled ChatArgs/CustomModel fields:
  * model_name at the ChatArgs level (what build_chat_body sends today and
    which works on the flat body)
  * custom_model.* (full 31-field struct)
  * model_auto_selection.strategy
  * agent_type / scene_location combinations
  * function / raw_chat_function / config_name

Note the flat body WORKS and contains model_name at top level, so start there
and add the envelope pieces one at a time.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 150) -> str:
    return " ".join(t.split())[:n]


def outcome(txt: str) -> str:
    if "output" in txt and "token_usage" in txt:
        return "STREAM OK"
    m = re.search(r'"code":(\d+)', txt)
    if m:
        return f"code={m.group(1)}"
    if "output" in txt:
        return "OUTPUT-no-usage"
    return "other"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = gw._headers()

    text = "Reply with one word: pong"
    sid = str(uuid.uuid4())
    ws = ["D:\\workspace\\re_music"]

    u = {"user_id": auth.creds.user_id, "user_type": "user",
         "user_is_login": True, "device_id": "4333646823299987"}
    ci = {"chat_session_id": sid, "device_id": "4333646823299987",
          "client_type": "ide", "workspace_folders": ws,
          "version_code": "20260212", "workspace_folder": ws[0],
          "icube_language": "zh-CN", "user_timezone": "Asia/Shanghai",
          "is_solo_mode": False, "window_type": "desktop",
          "git_repos": [], "local_git_repos": [], "git_metadata_dirs": [],
          "security_rules": [], "authorized_services": [],
          "ppe_env_name": "", "connect_session_id": str(uuid.uuid4()),
          "workspace_id": str(uuid.uuid4())}
    cp = {"code_window_type": "desktop", "agent_type": "builder",
          "app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_version": "3.4.7", "region": "CN"}

    async def post(body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}/api/ide/v1/chat", json=body,
                                 headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    def env(data, **over):
        e = {"service": "chat", "data": data, "user_info": u,
             "client_info": ci, "common_params": cp,
             "streamlined_common_params": cp}
        e.update(over)
        return e

    base_args = {
        "message_content": [{"type": "text", "text_content": text}],
        "workspace_folders": ws, "scene_location": 2,
        "agent_type": "builder",
        "agent": {"type": "builder", "name": "builder", "title": "Builder"},
        "message_id": str(uuid.uuid4()),
        "user_input": text, "chat_history": [],
    }

    log("=== try to satisfy model selection inside the real envelope ===")
    trials = {
        "no model field": {},
        "model_name=deepseek-v4.1-flash":
            {"model_name": "deepseek-v4.1-flash"},
        "model_name=auto": {"model_name": "auto"},
        "model_auto_selection.strategy=auto":
            {"model_auto_selection": {"strategy": "auto"}},
        "custom_model full":
            {"custom_model": {
                "provider": "", "is_preset": True, "config_source": 1,
                "model_name": "deepseek-v4.1-flash",
                "display_model_name": "DeepSeek-V4.1-Flash",
                "use_remote_service": True, "multimodal": True,
                "prompt_max_tokens": 936000,
                "reasoning_effort_level": "high"}},
        "custom_model+model_name":
            {"model_name": "deepseek-v4.1-flash",
             "model_auto_selection": {"strategy": "auto"},
             "custom_model": {"is_preset": True, "config_source": 1,
                              "model_name": "deepseek-v4.1-flash",
                              "use_remote_service": True}},
        "agent_type=chat scene=1":
            {"agent_type": "chat", "scene_location": 1},
        "agent_type=solo_agent":
            {"agent_type": "solo_agent",
             "agent": {"type": "solo_agent", "name": "solo_agent",
                       "title": "SOLO Agent"}},
        "function=chat": {"function": "chat"},
        "config_name": {"config_name": "deepseek-v4.1-flash"},
    }
    for label, extra in trials.items():
        data = {**base_args, **extra}
        code, txt = await post(env(data))
        o = outcome(txt)
        flag = "   <== SUCCESS" if o == "STREAM OK" else ""
        log(f"  {label:34} -> {o:12} {brief(txt, 90)}{flag}")

    log("\n=== control: flat body still works? ===")
    code, txt = await post({**base_args})
    log(f"  flat body -> {outcome(txt)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_e3003b.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
