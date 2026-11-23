"""Mine cueMain.js - the ai-server (cue-server) bundle, plain JavaScript.

This is the breakthrough target: cue-server is a Node process that runs
cueMain.js (3.5 MB of READABLE JS). It is the component that owns the
agent-mode stream (28 events) and it must therefore contain:
  * the real cloud base URL / domain selection
  * the real chat endpoints it calls
  * the request builders and SSE parsers

No decompilation needed - just read it.
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
BUNDLE = os.path.join(TRAE, r"resources\app\extensions\ai-completion"
                      r"\resource\aiserver\cueMain.js")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    if not os.path.exists(BUNDLE):
        log(f"!! missing {BUNDLE}")
        return 1
    with io.open(BUNDLE, "rb") as f:
        txt = f.read().decode("utf-8", "replace")
    log(f"cueMain.js: {len(txt)} chars\n")

    # --- 1. URLs ---------------------------------------------------------
    log("=" * 74)
    log("A. URL / host strings")
    log("=" * 74)
    urls = Counter()
    for m in re.finditer(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{4,120}",
                         txt):
        u = m.group(0).rstrip("'\"),;")
        urls[u] += 1
    for u, c in urls.most_common(45):
        log(f"  {u[:100]:100} x{c}")

    # --- 2. api paths ----------------------------------------------------
    log("\n" + "=" * 74)
    log("B. API paths")
    log("=" * 74)
    paths = Counter()
    for m in re.finditer(r"['\"`](/api/[A-Za-z0-9_/{}$:.-]{3,90})['\"`]", txt):
        paths[m.group(1)] += 1
    for p, c in paths.most_common(60):
        log(f"  {p:70} x{c}")

    # --- 3. env vars -----------------------------------------------------
    log("\n" + "=" * 74)
    log("C. env var names (domain/cloud related)")
    log("=" * 74)
    envs = Counter(re.findall(r"\b([A-Z][A-Z0-9_]{6,40})\b", txt))
    for name, c in envs.most_common(200):
        if any(k in name for k in ("URL", "DOMAIN", "HOST", "CLOUD",
                                   "APP_ID", "BASE", "ENDPOINT", "AGENT")):
            log(f"  {name:40} x{c}")

    # --- 4. domain selection logic ---------------------------------------
    log("\n" + "=" * 74)
    log("D. domain / baseUrl selection logic")
    log("=" * 74)
    for pat in (r"agent\.domain", r"bootConfig", r"BaseDomain",
                r"baseDomain", r"cloudUrl", r"getDomain"):
        for m in list(re.finditer(pat, txt))[:2]:
            s = max(0, m.start() - 350)
            log(f"\n  --- {pat} @{m.start()} ---")
            log("    " + " ".join(txt[s:m.start() + 450].split())[:750])

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_cuemain.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:15000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
