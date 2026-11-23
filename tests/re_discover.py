"""Discovery pass: what metadata can we mine out of the Trae binaries?

Goal (user directive): stop guessing, decompile the local client and recover the
COMPLETE call chain - which interfaces get called in what order for one LLM
request, which protocol each uses, and how request/response bodies are built and
parsed.

Before extracting anything we need to know which metadata classes are present.
This pass only COUNTS candidate anchors and prints a few samples, so the next
scripts can be targeted instead of speculative.

Candidate metadata classes:
  * serde field tables   -> "unknown field `x`", "missing field `x`"
                            (exact per-struct field lists, no guessing)
  * serde struct arities -> "struct X with N elements"
  * RPC handler tables   -> "[SomeHandler] unknown method: "
  * HTTP endpoint paths  -> "api/ide/v1/..."
  * SSE event kinds      -> "progress_notice" etc.
  * error codes          -> "all models failed", "record not found"
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
BINARIES = [
    (os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll"),
     "ai_agent.dll"),
    (os.path.join(TRAE, r"resources\app\modules\ai-agent\harness.dll"),
     "harness.dll"),
    (os.path.join(TRAE, r"resources\app\out\vs\workbench"
                 r"\workbench.desktop.main.js"), "workbench.js"),
    (os.path.join(TRAE, r"resources\app\out\main.js"), "main.js"),
]

# pattern -> regex (bytes)
PATTERNS: dict[str, bytes] = {
    "unknown field": rb"unknown field `",
    "missing field": rb"missing field `",
    "invalid type": rb"invalid type: ",
    "struct-with-N": rb"struct [A-Za-z0-9_]+ with \d+ element",
    "handler-unknown-method": rb"\[[A-Za-z]+Handler\] unknown method",
    "http api/ide path": rb"api/ide/v[0-9]/[a-z_/]+",
    "sse progress_notice": rb"progress_notice",
    "sse token_usage": rb"token_usage",
    "error all models failed": rb"all models failed",
    "error record not found": rb"record not found",
}

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def sample(buf: bytes, pat: bytes, n: int = 3, pad: int = 120) -> None:
    shown = 0
    start = 0
    while shown < n:
        p = buf.find(pat, start)
        if p < 0:
            break
        start = p + 1
        frag = buf[max(0, p - pad):p + pad + len(pat)]
        txt = re.sub(rb"[^\x20-\x7e]+", b" | ", frag)
        log("      " + txt.decode("ascii", "replace")[:340])
        shown += 1


def main() -> int:
    for path, label in BINARIES:
        if not os.path.exists(path):
            log(f"!! missing {label}: {path}")
            continue
        size = os.path.getsize(path)
        log("=" * 74)
        log(f"### {label}  ({size/1048576:.1f} MB)")
        log("=" * 74)
        with io.open(path, "rb") as f:
            buf = f.read()

        counts: Counter = Counter()
        for name, pat in PATTERNS.items():
            c = len(re.findall(pat, buf))
            counts[name] = c
            log(f"  {name:26} x{c}")
        log("")

        for name in ("unknown field", "missing field", "struct-with-N",
                     "handler-unknown-method", "error all models failed"):
            if counts.get(name):
                log(f"  --- samples: {name} ---")
                sample(buf, PATTERNS[name])
        log("")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_discover.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
