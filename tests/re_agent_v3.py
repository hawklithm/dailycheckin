"""Extract the full api/agent/v3/* surface - the ai-server LLM transport.

The reachability test proved api/ide/v1/chat only yields 3 of the 28 event
kinds. harness.dll (the ai-server process) meanwhile carries a whole separate
endpoint family:

    api/agent/v3/create_agent_task      api/agent/v3/resume_agent_task
    api/agent/v3/commit_toolcall_result api/agent/v3/interrupt
    api/agent/v3/query_history_state    api/agent/v3/sync_history_state
    api/agent/v3/llm_utils_chat         api/agent/v3/workflow/start
    api/agent/v3/generate_summary       api/agent/v3/use_fast_request
    api/agent/v3/dsl/templates          api/agent/v3/dsl/render/resources

This is very likely the REAL agent-mode LLM path (the one that emits
tool_call / thought / turn_completion). Splitting the concatenated run and
pairing each path with its neighbouring request/response struct names gives a
usable map.
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
HARNESS = os.path.join(TRAE, r"resources\app\modules\ai-agent\harness.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def clean(b: bytes, n: int = 1200) -> str:
    return re.sub(rb"[^\x20-\x7e]+", b" | ", b).decode("ascii", "replace")[:n]


def main() -> int:
    with io.open(HARNESS, "rb") as f:
        hb = f.read()

    # ---- 1. split the concatenated api/agent/v3 run ----------------------
    log("=" * 74)
    log("A. api/agent/v3/* ENDPOINTS (split from concatenated run)")
    log("=" * 74)
    # a new path starts with "api/"
    pat = re.compile(rb"api/(?:agent/v3|v1/chat|ide/v1|solo_hub/v1|"
                     rb"remote/v1|tokenx)[a-z0-9_/]*")
    found = []
    for m in pat.finditer(hb):
        found.append(m.group(0).decode("ascii", "replace"))
    uniq = list(dict.fromkeys(found))
    agent_paths = [p for p in uniq if p.startswith("api/agent/v3")]
    log(f"  api/agent/v3 paths: {len(agent_paths)}")
    for p in agent_paths:
        log(f"    {p}")

    other = [p for p in uniq if not p.startswith("api/agent/v3")]
    log(f"\n  other notable paths: {len(other)}")
    for p in other:
        if p.startswith(("api/v1/chat", "api/solo_hub", "api/tokenx",
                         "api/remote")):
            log(f"    {p}")

    # ---- 2. struct names near create_agent_task --------------------------
    log("\n" + "=" * 74)
    log("B. CONTEXT AROUND create_agent_task (request/response shape)")
    log("=" * 74)
    p = hb.find(b"create_agent_task")
    while p > 0:
        log(f"\n--- @{p} ---")
        log("  " + clean(hb[max(0, p - 500):p + 700], 1300))
        p = hb.find(b"create_agent_task", p + 1)
        if p > 0 and hb.find(b"create_agent_task", p + 1) < 0:
            break

    # ---- 3. structs whose names mention agent task / turn ----------------
    log("\n" + "=" * 74)
    log("C. AGENT-TASK RELATED STRUCTS")
    log("=" * 74)
    decl = re.compile(rb"struct ([A-Za-z0-9_]{3,60}) with (\d+) element")
    want = ("AgentTask", "Task", "Turn", "AgentRun", "Run", "Agent")
    seen = set()
    for m in decl.finditer(hb):
        name = m.group(1).decode("ascii", "replace")
        n = m.group(2).decode("ascii", "replace")
        if any(w in name for w in want) and (name, n) not in seen:
            seen.add((name, n))
    for name, n in sorted(seen):
        log(f"    {name:48} {n:>3} elements")
    log(f"\n  total: {len(seen)}")

    # ---- 4. llm_utils_chat context ---------------------------------------
    log("\n" + "=" * 74)
    log("D. llm_utils_chat / use_fast_request CONTEXT")
    log("=" * 74)
    for needle in (b"llm_utils_chat", b"use_fast_request",
                   b"resume_agent_task", b"query_history_state"):
        q = hb.find(needle)
        if q < 0:
            continue
        log(f"\n--- {needle.decode()} @{q} ---")
        log("  " + clean(hb[max(0, q - 400):q + 500], 1000))

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_agent_v3.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:16000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
