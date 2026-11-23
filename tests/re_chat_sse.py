"""Extract the ChatHandler method table + the SSE event contract precisely.

Two remaining gaps for the call-chain doc:

A) ChatHandler's full method list. The earlier pass drowned it in noise
   because ChatHandler appears dozens of times. Here we take the FIRST
   occurrence after src\\handler\\chat\\mod.rs, which carries the router's
   match arms ("resume_chat", "start_chat", ...).

B) The SSE event names the Rust side emits, and their payload fields. The
   client already showed us progress_notice/prompt/metadata/output/
   token_usage/done/error. This looks for the enum/struct that serialises
   them so the response contract is documented from the source of truth.
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
DLL = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def clean(b: bytes) -> str:
    return re.sub(rb"[^\x20-\x7e]+", b" ", b).decode("ascii", "replace")


def main() -> int:
    with io.open(DLL, "rb") as f:
        buf = f.read()

    # ---- A. ChatHandler router arms --------------------------------------
    log("=" * 74)
    log("A. ChatHandler ROUTER (chat/mod.rs + chat/handler.rs)")
    log("=" * 74)
    for anchor in (rb"apps\\icube_server_rs\\modules\\ai-agent\\src\\handler\\"
                   rb"chat\\mod\.rs",
                   rb"apps\\icube_server_rs\\modules\\ai-agent\\src\\handler\\"
                   rb"chat\\handler\.rs",
                   rb"apps\\icube_server_rs\\modules\\ai-agent\\src\\handler\\"
                   rb"chat\\client_info\.rs"):
        for m in re.finditer(anchor, buf):
            log(f"\n--- {m.group(0).decode()[-24:]} @{m.start()} ---")
            log("    " + clean(buf[m.start():m.start() + 700])[:1400])
            break

    # the "handle_<method>" family tells us the method names directly
    log("\n=== handle_* methods present ===")
    handles = sorted({m.group(0).decode("ascii", "replace")
                      for m in re.finditer(rb"handle_[a-z_]{3,40}", buf)})
    for h in handles:
        log(f"    {h}")

    # ---- B. SSE event enum ------------------------------------------------
    log("\n" + "=" * 74)
    log("B. SSE EVENT CONTRACT")
    log("=" * 74)
    # The client-side event names, and the Rust names near them
    for ev in ("progress_notice", "prompt", "metadata", "output",
               "token_usage", "done", "error"):
        p = buf.find(ev.encode())
        if p < 0:
            log(f"  {ev}: not in DLL")
            continue
        log(f"\n--- {ev} @{p} ---")
        log("    " + clean(buf[max(0, p - 300):p + 300])[:700])

    # struct declarations whose names look like stream events
    log("\n=== stream/event struct declarations ===")
    decl = re.compile(rb"struct ([A-Za-z0-9_]{3,60}) with (\d+) element")
    want = ("Event", "Chunk", "Stream", "Delta", "Output", "Usage",
            "Metadata", "Progress", "Prompt", "Token")
    seen = set()
    for m in decl.finditer(buf):
        name = m.group(1).decode("ascii", "replace")
        n = m.group(2).decode("ascii", "replace")
        if any(w in name for w in want) and (name, n) not in seen:
            seen.add((name, n))
            log(f"    {name:44} {n:>3} elements")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_chat_sse.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:18000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
