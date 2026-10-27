"""Decode error 3003 and iterate on the real-envelope request.

Sending the decompiled `Request` envelope to v1/chat produced a NEW error code
(3003) instead of the previous 2001/4011 family - proof the server is now
parsing a structure it recognises and is complaining about a specific missing
field.

Step 1: find what 3003 means. The DLL holds the error-code enum / message
strings; search for the code near message text.
Step 2: bisect which ChatArgs/context field the server wants, since 3003 is
presumably a validation failure.
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

DLL = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
       r"\resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 300) -> str:
    return " ".join(t.split())[:n]


def main_codes() -> int:
    """Look up what 3003 is in the binary's error vocabulary."""
    with io.open(DLL, "rb") as f:
        buf = f.read()
    log("=== searching DLL for 3003 context ===")
    n = 0
    start = 0
    while n < 12:
        p = buf.find(b"3003", start)
        if p < 0:
            break
        start = p + 1
        lo = max(0, p - 400)
        hi = min(len(buf), p + 400)
        frag = buf[lo:hi]
        # keep printable-ish
        txt = re.sub(rb"[^\x20-\x7e]+", b" | ", frag).decode("ascii",
                                                            "replace")
        if len(txt.strip(" |")) < 20:
            continue
        log(f"\n  @{p}: {txt[:700]}")
        n += 1

    # also the numeric code enums often appear as plain integers in message
    # tables; look for likely message text near "code" strings
    for needle in (b"error_code", b"ErrorCode", b"invalid_param",
                   b"param is invalid", b"InvalidParameter"):
        c = buf.count(needle)
        log(f"\n  {needle.decode():22} x{c}")
        if 0 < c < 40:
            p = buf.find(needle)
            txt = re.sub(rb"[^\x20-\x7e]+", b" | ",
                         buf[max(0, p - 200):p + 400]).decode(
                             "ascii", "replace")
            log(f"     ctx: {txt[:500]}")
    return 0


async def async_part() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = gw._headers()

    text = "Reply with one word: pong"
    sid = str(uuid.uuid4())

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
    cp = {"code_window_type": "desktop", "agent_type": "builder",
          "app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
          "app_version": "3.4.7", "region": "CN"}
    custom_model = {
        "provider": "", "is_preset": True, "config_source": 1,
        "model_name": "deepseek-v4.1-flash",
        "display_model_name": "DeepSeek-V4.1-Flash",
        "use_remote_service": True, "multimodal": True,
        "prompt_max_tokens": 936000, "reasoning_effort_level": "high",
    }

    def args(**over):
        a = {
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
        a.update(over)
        return a

    def env(data, **over):
        e = {"service": "chat", "data": data, "user_info": u,
             "client_info": client_info, "common_params": cp,
             "streamlined_common_params": cp}
        e.update(over)
        return e

    async def post(body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}/api/ide/v1/chat", json=body,
                                 headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("\n\n=== bisect: add fields to clear 3003 ===")
    trials = {
        "as-is": args(),
        "+user_input": args(user_input=text),
        "+chat_history": args(user_input=text, chat_history=[]),
        "+session_id": args(user_input=text, chat_history=[],
                            session_id=sid),
        "+message_id": args(user_input=text, chat_history=[], session_id=sid,
                            message_id=str(uuid.uuid4())),
        "+agent": args(user_input=text, chat_history=[], session_id=sid,
                       message_id=str(uuid.uuid4()),
                       agent={"type": "builder", "name": "builder",
                              "title": "Builder"}),
    }
    for label, a in trials.items():
        code, txt = await post(env(a))
        m = re.search(r'"code":(\d+)', txt)
        ecode = m.group(1) if m else "-"
        ok = "output" in txt
        log(f"  {label:16} -> http {code} code={ecode} "
            f"{'OUTPUT!' if ok else ''} {brief(txt, 120)}")
    return 0


def main() -> int:
    main_codes()
    asyncio.run(async_part())
    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_e3003.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
