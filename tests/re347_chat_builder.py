"""Find exactly how the renderer builds its chat request.

Goal (restated by the user): V1 works but only as "chat mode"; real Trae is an
AGENT loop (chat_process_version v3, native tool calls). We want to know which
request shape produces that behaviour, so we can reproduce it.

So instead of guessing HTTP bodies, find the renderer code that assembles the
chat request and dump it. Searches workbench.js for the request builder.
"""
from __future__ import annotations

import io
import os
import re
import sys

WB = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    if not os.path.exists(WB):
        log(f"!! missing {WB}")
        return 1
    with io.open(WB, "rb") as f:
        txt = f.read().decode("latin-1")
    log(f"workbench.js {len(txt)} chars\n")

    def show(pattern, before=300, after=900, limit=3, label=""):
        log(f"=== {label or pattern} ===")
        n = 0
        for m in re.finditer(pattern, txt):
            seg = txt[max(0, m.start() - before):m.start() + after]
            log(re.sub(r"\s+", " ", seg)[:1800])
            log("-" * 90)
            n += 1
            if n >= limit:
                break
        log("")

    show(r'agent_process_support', 300, 800, 3)
    show(r'chat_process_version', 300, 800, 3)
    show(r'agent_type:\s*"solo_agent"', 300, 900, 3)
    show(r'createChatRequestObject', 200, 1200, 2)
    show(r'scene_location', 250, 800, 3)
    show(r'requestTracking', 200, 700, 3)

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_chatbuilder.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:9000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
