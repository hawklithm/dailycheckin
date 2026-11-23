"""Does the server actually SEND the 28 event kinds? (test the assumption)

User's premise: "if we use the same call logic as the client, we will get the
remote config and the whole flow will work."

That is testable. The decompiled enum (28 events) comes from harness.dll, which
is the AI-SERVER process - and ai-server talks to the server. But the SSE
stream we consume comes from api/ide/v1/chat. If that endpoint only ever emits
a subset, then "same call logic" cannot conjure the rest.

This runs a realistic chat and records EVERY distinct `event:` name seen, then
compares against the 28-event vocabulary. It also tries a few extra request
shapes (solo agent, plan mode) that might switch on richer streams.
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

KNOWN_28 = [
    "task_created", "thought", "tool_call", "revoke", "turn_completion",
    "progress_notice", "missing_history", "history", "user_message",
    "required_context", "obtain_context", "model_config", "tool_cache_data",
    "compact_finish", "compact_token_usage", "chat_memory_trigger",
    "queuing", "token_usage", "context_usage", "done", "timing_cost",
    "agent_identity", "sub_agent_create", "sub_agent_finish", "agent_status",
    "agent_resume", "project_name", "dsl_extension_log",
]


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def events(txt: str) -> list[str]:
    return re.findall(r"^event:\s*(\S+)", txt, re.M)


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = gw._headers()
    ws = ["D:\\workspace\\re_music"]

    async def post(body, timeout=120):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}/api/ide/v1/chat", json=body,
                                 headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    text = "List the files in the current directory, then say done."
    base = {
        "user_input": text, "session_id": str(uuid.uuid4()),
        "chat_history": [],
        "message_content": [{"type": "text", "text_content": text}],
        "message_id": str(uuid.uuid4()),
        "agent_type": "builder", "scene_location": 2,
        "agent": {"type": "builder", "name": "builder", "title": "Builder"},
        "workspace_folders": ws,
    }

    shapes = {
        "builder (default)": dict(base),
        "solo_agent": {**base, "agent_type": "solo_agent",
                       "agent": {"type": "solo_agent", "name": "solo_agent",
                                 "title": "SOLO Agent"}},
        "plan mode": {**base, "is_in_plan_mode": True},
        "chat/agent_type=chat": {**base, "agent_type": "chat",
                                 "scene_location": 1},
    }

    all_seen: set[str] = set()
    for label, body in shapes.items():
        code, txt = await post(body)
        ev = events(txt)
        uniq = sorted(set(ev))
        all_seen.update(uniq)
        log(f"\n=== {label} -> http {code}, {len(ev)} events ===")
        log("    distinct: " + ", ".join(uniq))

    log("\n" + "=" * 70)
    log("=== VERDICT: which of the 28 are actually reachable? ===")
    log("=" * 70)
    seen = [e for e in KNOWN_28 if e in all_seen]
    unseen = [e for e in KNOWN_28 if e not in all_seen]
    log(f"  reachable ({len(seen)}): " + ", ".join(seen))
    log(f"\n  NOT reachable ({len(unseen)}): " + ", ".join(unseen))
    extra = sorted(all_seen - set(KNOWN_28))
    if extra:
        log(f"\n  seen but not in the 28 list: " + ", ".join(extra))

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_reachable_events.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
