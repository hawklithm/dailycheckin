"""Recover the real LLM request schema from ai_agent.dll by static analysis.

Rationale (user's idea): stop trying to capture the traffic, decompile the
implementation instead and reimplement it in Python.

Why this can actually work on this binary:
  * it is Rust, so serde leaves the struct field names in the image as
    plaintext, concatenated into runs like
        is_presetconfig_sourcedisplay_model_namecustom_model_uniq_id...
    which is literally ModelInfo's field list.
  * serde also emits "struct X with N elements" strings, giving the arity.
  * panic/log format strings embed source paths
    (apps\\icube_server_rs\\modules\\ai-agent\\src\\...), which map the
    module layout.

So mine the image for: (a) field-name clusters around LLM/chat anchors,
(b) "struct ... with N elements" declarations, (c) source paths, (d) any
surviving Rust symbol names for the llm adapter.
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

DLL = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
       r"\resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


# anchors that should sit inside the request struct we want
ANCHORS = [
    b"llm_raw_chat",
    b"raw_chat_function",
    b"user_input",
    b"chat_history",
    b"workspace_folders",
    b"message_content",
]

PRINTABLE = set(range(0x20, 0x7f))


def ascii_run(buf: bytes, pos: int, back: int = 1500, fwd: int = 2500):
    """Expand around pos to the enclosing printable ASCII run."""
    lo = max(0, pos - back)
    hi = min(len(buf), pos + fwd)
    # walk left while printable
    i = pos
    while i > lo and buf[i - 1] in PRINTABLE:
        i -= 1
    j = pos
    while j < hi - 1 and buf[j] in PRINTABLE:
        j += 1
    return buf[i:j]


def main() -> int:
    if not os.path.exists(DLL):
        log(f"!! missing {DLL}")
        return 1
    log(f"loading {DLL} ({os.path.getsize(DLL)/1048576:.1f} MB)")
    with io.open(DLL, "rb") as f:
        buf = f.read()
    log(f"loaded {len(buf)} bytes\n")

    # --- 1. field-name clusters around anchors -------------------------------
    log("=" * 70)
    log("1. FIELD-NAME CLUSTERS AROUND LLM ANCHORS")
    log("=" * 70)
    seen: set[bytes] = set()
    for anchor in ANCHORS:
        n = 0
        start = 0
        while True:
            p = buf.find(anchor, start)
            if p < 0:
                break
            start = p + 1
            run = ascii_run(buf, p)
            if run in seen:
                continue
            seen.add(run)
            # only interesting if it looks like a struct field list
            if len(run) < 40:
                continue
            log(f"\n--- anchor={anchor.decode()} @{p} "
                f"(run {len(run)} chars)")
            log("    " + run.decode("ascii", "replace")[:2400])
            n += 1
            if n >= 6:
                break

    # --- 2. serde struct arities -------------------------------------------
    log("\n" + "=" * 70)
    log("2. SERDE 'struct X with N elements' DECLARATIONS (LLM-related)")
    log("=" * 70)
    pat = re.compile(rb"struct ([A-Za-z0-9_]{3,60}) with (\d+) element")
    structs: Counter = Counter()
    for m in pat.finditer(buf):
        structs[(m.group(1).decode("ascii", "replace"),
                 int(m.group(2)))] += 1
    keys = ["Chat", "Llm", "LLM", "Message", "Model", "Agent", "Request",
            "Response", "Config", "Tool", "Stream", "Session"]
    hits = [(name, n, c) for (name, n), c in structs.items()
            if any(k in name for k in keys)]
    hits.sort(key=lambda t: -t[2])
    log(f"  total distinct structs: {len(structs)}")
    log(f"  LLM/chat-related: {len(hits)}\n")
    for name, n, c in hits[:80]:
        log(f"    {name:46} {n:3} elements   x{c}")

    # --- 3. source paths ----------------------------------------------------
    log("\n" + "=" * 70)
    log("3. SOURCE PATHS (module layout)")
    log("=" * 70)
    pp = re.compile(rb"apps[\\/]icube_server_rs[\\/][A-Za-z0-9_\\/.-]{3,120}\.rs")
    paths: Counter = Counter()
    for m in pp.finditer(buf):
        paths[m.group(0).decode("ascii", "replace")] += 1
    log(f"  distinct paths: {len(paths)}")
    for p, c in paths.most_common(60):
        log(f"    {p}  x{c}")

    # --- 4. surviving rust symbols -----------------------------------------
    log("\n" + "=" * 70)
    log("4. RUST SYMBOL-ISH NAMES for the llm adapter")
    log("=" * 70)
    for sym in (b"infrastructure::adapter::llm",
                b"llm_raw_chat_custom_model",
                b"build_request", b"LlmAdapter", b"llm_adapter"):
        c = buf.count(sym)
        log(f"  {sym.decode():40} x{c}")
        if c and c < 200:
            p = buf.find(sym)
            log("      ctx: " + ascii_run(buf, p, 200, 400)
                .decode("ascii", "replace")[:600])

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_decomp_structs.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
