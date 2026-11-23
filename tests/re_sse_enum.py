"""Extract the COMPLETE SSE event enum and the chat turn state machine.

harness.dll contains the authoritative event-name table as one concatenated
run:

    task_created thought tool_call revoke turn_completion progress_notice
    missing_history history user_message required_context obtain_context
    model_config tool_cache_data compact_finish compact_token_usage
    chat_memory_trigger queuing token_usage context_usage done timing_cost
    agent_identity sub_agent_create sub_agent_finish agent_status
    agent_resume project_name dsl_extension_log

That is the real wire vocabulary - far richer than the 7 events our parser
handles (progress_notice/prompt/metadata/output/token_usage/done/error).
Several of these carry exactly the capability the user wants and that we
currently ignore: tool_call, thought, model_config, context_usage, queuing,
turn_completion, compact_*.

This dumps that table plus neighbouring enum data, and looks for the state
machine transition names.
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
HARNESS = os.path.join(TRAE, r"resources\app\modules\ai-agent\harness.dll")
AGENT = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def clean(b: bytes, keep: int = 2000) -> str:
    return re.sub(rb"[^\x20-\x7e]+", b" | ", b).decode("ascii",
                                                       "replace")[:keep]


# the event names harvested from the harness.dll run
EVENTS = [
    "task_created", "thought", "tool_call", "revoke", "turn_completion",
    "progress_notice", "missing_history", "history", "user_message",
    "required_context", "obtain_context", "model_config", "tool_cache_data",
    "compact_finish", "compact_token_usage", "chat_memory_trigger",
    "queuing", "token_usage", "context_usage", "done", "timing_cost",
    "agent_identity", "sub_agent_create", "sub_agent_finish", "agent_status",
    "agent_resume", "project_name", "dsl_extension_log",
]


def main() -> int:
    with io.open(HARNESS, "rb") as f:
        hb = f.read()
    with io.open(AGENT, "rb") as f:
        ab = f.read()

    log("=" * 74)
    log("A. SSE EVENT VOCABULARY (harness.dll run @182384857)")
    log("=" * 74)
    for i, ev in enumerate(EVENTS, 1):
        log(f"  {i:2}. {ev}")
    log(f"\n  total: {len(EVENTS)} event kinds")
    log("\n  our server.py currently handles only:")
    log("    progress_notice, prompt, metadata, output, token_usage, done,"
        " error")
    log("  -> MISSING handling for: " + ", ".join(
        e for e in EVENTS if e not in
        {"progress_notice", "token_usage", "done"}))

    log("\n" + "=" * 74)
    log("B. SURROUNDING BYTES (more enum data / field names)")
    log("=" * 74)
    p = hb.find(b"task_createdthought")
    if p < 0:
        p = hb.find(b"progress_notice")
    log(clean(hb[max(0, p - 900):p + 900], 1800))

    log("\n" + "=" * 74)
    log("C. per-event presence in each binary")
    log("=" * 74)
    log(f"  {'event':26} {'harness':>9} {'ai_agent':>9}")
    for ev in EVENTS:
        log(f"  {ev:26} {hb.count(ev.encode()):>9} "
            f"{ab.count(ev.encode()):>9}")

    log("\n" + "=" * 74)
    log("D. CHAT TURN STATE MACHINE candidates")
    log("=" * 74)
    for needle in (b"turn_completion", b"queuing", b"agent_status",
                   b"required_context", b"obtain_context", b"compact_finish"):
        q = ab.find(needle)
        where = "ai_agent"
        if q < 0:
            q = hb.find(needle)
            where = "harness"
        if q < 0:
            continue
        src = ab if where == "ai_agent" else hb
        log(f"\n--- {needle.decode()} ({where}) @{q} ---")
        log("    " + clean(src[max(0, q - 400):q + 400], 800))

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_sse_enum.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:16000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
