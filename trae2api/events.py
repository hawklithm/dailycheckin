"""Event taxonomy recovered from the client binaries, with our coverage.

The 28 event kinds live in harness.dll (the ai-server process). Verified by
live probing: api/ide/v1/chat - the only inference path that works for this
account - emits just a subset. So this module documents the full vocabulary,
marks what is actually reachable today, and defines how each reachable event
should be interpreted.

Keeping the full list matters for two reasons:
  1. if a richer path (api/agent/v3/*) ever becomes usable, the vocabulary is
     already captured;
  2. unknown events must never be silently dropped - they are counted and
     surfaced so behaviour changes are noticed rather than guessed at.
"""
from __future__ import annotations

# --- full vocabulary (order preserved from the binary's string table) -----
ALL_EVENTS = [
    "task_created", "thought", "tool_call", "revoke", "turn_completion",
    "progress_notice", "missing_history", "history", "user_message",
    "required_context", "obtain_context", "model_config", "tool_cache_data",
    "compact_finish", "compact_token_usage", "chat_memory_trigger",
    "queuing", "token_usage", "context_usage", "done", "timing_cost",
    "agent_identity", "sub_agent_create", "sub_agent_finish", "agent_status",
    "agent_resume", "project_name", "dsl_extension_log",
]

# --- events observed from api/ide/v1/chat (the working path) --------------
# Note: "prompt" and "metadata" are NOT in the 28-event list but ARE emitted
# by v1/chat, so the wire contract of this endpoint differs from the agent
# vocabulary. Both lists are needed.
V1_CHAT_EVENTS = [
    "progress_notice", "prompt", "metadata", "output", "token_usage",
    "done", "error",
]

# --- what each reachable event carries ------------------------------------
# Derived from live captures. Documented so the parser's intent is explicit.
EVENT_SEMANTICS = {
    "progress_notice": "stage notification, e.g. construct_prompt; no content",
    "prompt": "prompt build info; string/messages are null on this endpoint",
    "metadata": ("session/model metadata. Carries session_id, ab_versions, "
                 "app_version; model is empty string on v1/chat"),
    "output": ("the only content-bearing event: response (text), "
               "reasoning_content (thinking), tool_calls (always null on "
               "v1/chat), phase"),
    "token_usage": ("per-name usage totals: prompt_tokens, completion_tokens, "
                    "total_tokens, cache_* and reasoning_* counters"),
    "done": "terminator, carries finish_reason",
    "error": "failure, carries code/message; codes seen: 2001, 3003, 4001, "
             "4011, 4000105",
}

# --- error codes seen in practice, with meaning ---------------------------
ERROR_CODES = {
    "2001": ("config lookup / function resolution failed. Seen as "
             "'failed to get app config: record not found' and "
             "'function is empty, cannot resolve model by usage'"),
    "3003": "all models failed (dispatch reached, model selection failed)",
    "4001": ("invalid param, or 'config item is empty for config opt' with the "
             "full lookup key printed"),
    "4011": ("rate limited. PROVEN endpoint/function scoped, not account "
             "quota: v1/chat streams while agent/v3 4011s simultaneously"),
    "4000105": "missing history count exceeded for session (too many rebuilds)",
}

# --- informational events that must not be treated as content ------------
INFORMATIONAL = {"progress_notice", "prompt", "metadata", "token_usage",
                 "done", "error"}


def is_known(event: str) -> bool:
    return event in ALL_EVENTS or event in V1_CHAT_EVENTS


def describe(event: str) -> str:
    return EVENT_SEMANTICS.get(event, "(undocumented event)")


def coverage() -> str:
    """Human-readable coverage report."""
    reachable = [e for e in V1_CHAT_EVENTS]
    unreachable = [e for e in ALL_EVENTS if e not in V1_CHAT_EVENTS]
    lines = [
        f"agent vocabulary: {len(ALL_EVENTS)} events",
        f"v1/chat reachable: {len(reachable)} events -> {', '.join(reachable)}",
        "",
        f"NOT reachable on v1/chat ({len(unreachable)}):",
    ]
    for e in unreachable:
        lines.append(f"    {e:24} {describe(e)}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(coverage())
