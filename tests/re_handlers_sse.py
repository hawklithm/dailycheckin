"""Extract per-handler RPC method names and the SSE event vocabulary.

Two things the call-chain document needs:

A) Which RPC methods each handler serves. Method names appear as plaintext
   immediately before each "[<Handler>] unknown method: " log string, as the
   dispatch match arms. Dumping the surrounding run gives the method list.

B) The SSE event vocabulary of the chat stream. The client parses events like
   "progress_notice"/"prompt"/"metadata"/"output"/"token_usage"/"done"/"error".
   Their Rust-side names and payload structs tell us the exact response
   contract, which is what "how to parse the response" depends on.
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
DLL = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    with io.open(DLL, "rb") as f:
        buf = f.read()

    # ---- A. per-handler method clusters -----------------------------------
    log("=" * 74)
    log("A. HANDLER DISPATCH CLUSTERS")
    log("=" * 74)
    for m in re.finditer(rb"\[([A-Za-z]+Handler)\] unknown method", buf):
        p = m.start()
        handler = m.group(1).decode("ascii", "replace")
        # walk back over the printable run
        i = p
        while i > 0 and 0x20 <= buf[i - 1] < 0x7f:
            i -= 1
        run = buf[i:p].decode("ascii", "replace")
        # method names are snake_case; pull them out
        meths = re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){0,4}\b", run)
        # keep only plausible method names (len>2, has underscore or is known)
        keep = [x for x in meths if len(x) > 2 and "_" in x]
        log(f"\n--- {handler} @{p}  ({len(keep)} snake tokens)")
        log("    " + ", ".join(dict.fromkeys(keep))[:1500])

    # ---- B. SSE event vocabulary ------------------------------------------
    log("\n" + "=" * 74)
    log("B. SSE EVENT VOCABULARY (client-parsed event names)")
    log("=" * 74)
    events = ["progress_notice", "prompt", "metadata", "output", "token_usage",
              "done", "error", "tool_call", "tool_result", "thinking",
              "reasoning", "meta", "ping", "usage", "summary", "title"]
    for e in events:
        c = buf.count(e.encode())
        log(f"  {e:18} x{c}")

    # The stream chunk struct names
    log("\n=== stream/chunk related struct declarations ===")
    decl = re.compile(rb"struct ([A-Za-z0-9_]{3,60}) with (\d+) element")
    seen = Counter()
    for m in decl.finditer(buf):
        name = m.group(1).decode("ascii", "replace")
        n = int(m.group(2))
        if any(k in name for k in ("Stream", "Chunk", "Event", "Output",
                                   "Delta", "Sse", "SSE", "Response",
                                   "Token", "Usage", "Progress")):
            seen[(name, n)] += 1
    for (name, n), c in sorted(seen.items(), key=lambda kv: -kv[1])[:60]:
        log(f"    {name:44} {n:3} elements  x{c}")

    # ---- C. the output/event payload field clusters -----------------------
    log("\n" + "=" * 74)
    log("C. FIELD CLUSTERS AROUND STREAM EVENT NAMES")
    log("=" * 74)
    for anchor in (b"reasoning_content", b"tool_calls", b"finish_reason",
                   b"prompt_completion_id", b"cache_read_input_tokens"):
        p = buf.find(anchor)
        if p < 0:
            continue
        i = p
        while i > 0 and 0x20 <= buf[i - 1] < 0x7f:
            i -= 1
        j = p
        while j < len(buf) - 1 and 0x20 <= buf[j] < 0x7f:
            j += 1
        run = buf[i:j].decode("ascii", "replace")
        log(f"\n--- {anchor.decode()} ---")
        log("    " + run[:1600])

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_handlers_sse.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
