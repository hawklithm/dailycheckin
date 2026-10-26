"""Test whether the missing client_info context layer changes anything.

Field census result that motivated this: the fields our V1 HTTP body sends
(message_content, scene_location, parsed_query, agent_process_support,
chat_process_version) occur ZERO times in workbench.js. Meanwhile the real
renderer request, dumped in full from convertReqToRustPayload, carries a large
client_info context block we never send: git_repos, local_git_repos,
git_metadata_dirs, security_rules, workspace_id, project_id,
chat_session_id, connect_session_id, permission_profile_id,
agent_task_service_strategy, ckg_* flags, web_fetch_* config, user_timezone,
authorized_services, terminal_info, agent_run_info, ...

Hypothesis: V1 feels like "just chat mode" precisely because that context is
absent, so the server falls back to a bare chat template. If adding context
changes the response (different prompt template, tools offered, progress
events), we learn exactly where the behavioural gap lives.

This sends the V1 body enriched with a realistic client_info / common_params
layer and diffs the event shapes against the bare V1 baseline.
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

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 200) -> str:
    return " ".join(t.split())[:n]


def events(txt: str) -> list[str]:
    return re.findall(r"^event:\s*(\S+)", txt, re.M)


def prompt_name(txt: str) -> str:
    m = re.search(r'"name":"([^"]*prompts?)"', txt)
    return m.group(1) if m else "-"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = gw._headers()          # the header set that provably streams today

    text = "Reply with one word: pong"
    sid = str(uuid.uuid4())
    base = {"user_input": text, "session_id": sid, "chat_history": [],
            "message_id": str(uuid.uuid4()),
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder",
                      "title": "Builder"}}

    async def post(path, body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("=== baseline: bare V1 body ===")
    code, b0 = await post("/api/ide/v1/chat", dict(base))
    log(f"  -> {code} events={events(b0)}")
    log(f"     prompt={prompt_name(b0)}")

    # the context layer the real renderer sends
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
        "is_worktree": False, "is_workspace_folder_changed": False,
        "workspace_folders": ["D:\\workspace\\re_music"],
        "authorized_services": [],
    }
    common_params = {"code_window_type": "desktop",
                     "agent_tool_approval_type": "full_access",
                     "agent_type": "builder", "app_id":
                     "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                     "app_version": "3.4.7", "region": "CN"}

    trials = {
        "+client_info only": dict(base, client_info=client_info),
        "+common_params only": dict(base, common_params=common_params),
        "+both": dict(base, client_info=client_info,
                      common_params=common_params),
    }

    log("\n=== with the context layer the real client sends ===")
    for label, body in trials.items():
        code, txt = await post("/api/ide/v1/chat", body)
        ev = events(txt)
        same_ev = ev == events(b0)
        log(f"  {label:22} -> {code} events={ev}")
        log(f"     prompt={prompt_name(txt)}  "
            f"{'(identical events)' if same_ev else '<== EVENTS CHANGED'}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_contextlayer.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
