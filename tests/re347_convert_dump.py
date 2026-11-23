"""Dump convertReqToRustPayload in full - the real renderer->sidecar builder.

Key finding from the field census: the fields our V1 HTTP body uses
(message_content, scene_location, parsed_query, agent_process_support,
chat_process_version) occur ZERO times in workbench.js. So the HTTP shape we
send is NOT what the real client sends; the real one is assembled by
convertReqToRustPayload and delivered over mojo, not HTTP.

Dumping that function in full tells us what a real request actually contains,
so gap analysis against V1 becomes concrete rather than guesswork.
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

    # brace-match the function body starting at its opening brace
    i = txt.find("async convertReqToRustPayload(")
    if i < 0:
        log("!! convertReqToRustPayload not found")
        return 1
    j = txt.find("{", i)
    depth = 0
    end = j
    for k in range(j, min(j + 40000, len(txt))):
        if txt[k] == "{":
            depth += 1
        elif txt[k] == "}":
            depth -= 1
            if depth == 0:
                end = k + 1
                break
    body = txt[i:end]
    log(f"=== convertReqToRustPayload ({len(body)} chars) ===")
    log(re.sub(r"\s+", " ", body))
    log("")

    # field names referenced inside
    fields = sorted(set(re.findall(r"\b([a-z_][a-z0-9_]{3,30})\s*:", body)))
    log(f"=== field-like keys referenced ({len(fields)}) ===")
    log(", ".join(fields))

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_converttxt.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:14000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
