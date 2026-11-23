"""Find the REAL host that serves api/v1/chat/* and api/agent/v3/*.

api/v1/chat/* 404'd on trae-api-cn.mchost.guru. The strings sit in
harness.dll next to TTNetConfig / httpDNS / tncHost / SaasSlardarRouting, so
the ai-server resolves its own host via TTNet's httpDNS - likely a DIFFERENT
domain than the sidecar's.

Approach: harvest every hostname-looking string in harness.dll and look for
ones distinct from the known three (api.trae.cn, api.trae.com.cn,
trae-api-cn.mchost.guru).
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
HARNESS = os.path.join(TRAE, r"resources\app\modules\ai-agent\harness.dll")
AGENT = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

KNOWN = {"api.trae.cn", "api.trae.com.cn", "trae-api-cn.mchost.guru",
         "bytegate-sg.byteintlapi.com"}

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


HOST_RE = re.compile(
    rb"\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    rb"(?:com|cn|net|org|guru|io|co|internal|local|top|xyz|api|dev))"
    rb"(?::\d{2,5})?\b")


def main() -> int:
    for path, label in ((HARNESS, "harness.dll"), (AGENT, "ai_agent.dll")):
        with io.open(path, "rb") as f:
            buf = f.read()
        log("=" * 74)
        log(f"### {label}")
        log("=" * 74)
        hits: Counter = Counter()
        for m in HOST_RE.finditer(buf):
            h = m.group(1).decode("ascii", "replace").lower()
            if len(h) < 6 or h.startswith(("www.", "schemas.")):
                continue
            hits[h] += 1
        interesting = {h: c for h, c in hits.items() if h not in KNOWN}
        log(f"  distinct host-like strings: {len(hits)}")
        log(f"  known: {sorted(set(hits) & KNOWN)}")
        log("\n  --- unknown hosts (candidates) ---")
        for h, c in sorted(interesting.items(), key=lambda kv: -kv[1])[:70]:
            log(f"    {h:56} x{c}")
        log("")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_hosts.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
