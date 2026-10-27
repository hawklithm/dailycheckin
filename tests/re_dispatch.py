"""Extract the RPC dispatch tables: which service/method pairs exist.

The sidecar logs "[<Handler>] unknown method: " per handler, and the method
names live in the adjacent dispatch match arms as plaintext. Harvesting these
gives the authoritative list of RPC service/method pairs - i.e. the actual
interface surface of the local agent, which is what the call-chain analysis
needs.

Also harvests the HTTP endpoint strings (api/ide/v1/...) so we can map
RPC-side intent onto the HTTP calls the sidecar makes to the server.
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import defaultdict

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
DLL = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def printable_runs(buf: bytes, minlen: int = 6, maxlen: int = 400):
    """Yield (offset, ascii-run) for runs of printable bytes."""
    run_start = None
    n = len(buf)
    for i in range(n):
        b = buf[i]
        ok = 0x20 <= b < 0x7f
        if ok and run_start is None:
            run_start = i
        elif not ok and run_start is not None:
            ln = i - run_start
            if minlen <= ln <= maxlen:
                yield run_start, buf[run_start:i]
            run_start = None


def main() -> int:
    with io.open(DLL, "rb") as f:
        buf = f.read()
    log(f"ai_agent.dll {len(buf)} bytes\n")

    # ---- 1. handler method tables -----------------------------------------
    # the log format string tells us the handler name
    handler_re = re.compile(rb"\[([A-Za-z]+Handler)\] unknown method")
    handlers = []
    for m in handler_re.finditer(buf):
        handlers.append((m.start(), m.group(1).decode("ascii", "replace")))
    log(f"=== handlers emitting 'unknown method': {len(handlers)} ===")
    names = sorted({h for _, h in handlers})
    log("    " + ", ".join(names))

    # ---- 2. method-name clusters ------------------------------------------
    # Method names are lowercase snake_case; gather every snake_case token and
    # count, then show the ones near known handlers.
    snake = re.compile(rb"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,4}\b")
    freq = defaultdict(int)
    for m in snake.finditer(buf):
        freq[m.group(0)] += 1
    log(f"\n=== distinct snake_case tokens: {len(freq)} ===")

    # known RPC-ish method names from the JS side (handoff section 4)
    known = [
        "create_chat_session", "get_messages", "chat", "stop_chat",
        "get_sessions", "delete_session", "slash_list", "get_user_configuration",
        "update_user_configuration", "create_agent_task", "commit_toolcall_result",
        "save_toolcall_result", "model_list", "get_model_list",
        "batch_get_detail_param", "llm_raw_chat", "get_agents",
        "create_or_polish_agent_via_llm", "generate_commit_message",
    ]
    log("\n=== presence of known method names ===")
    for k in known:
        c = buf.count(k.encode())
        log(f"    {k:36} x{c}")

    # ---- 3. HTTP endpoint strings -----------------------------------------
    log("\n=== HTTP endpoint strings ===")
    path_re = re.compile(rb"api/ide/v[0-9]/[a-z0-9_/]+")
    paths = sorted({m.group(0).decode("ascii", "replace")
                    for m in path_re.finditer(buf)})
    for p in paths:
        log(f"    {p}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_dispatch.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
