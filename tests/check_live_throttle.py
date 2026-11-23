"""Decisive test: is the ACCOUNT throttled, or just our synthetic request?

Right now llm_raw_chat answers 4011 to us, while the account still shows 61%
credits left. Two very different worlds:

  A. The account (or this machine/IP) is throttled right now
     -> nothing we send can succeed; Trae itself would also be failing.
  B. The account is fine and Trae itself works
     -> our request is missing something; 4011 is fixable.

The plaintext renderer logs record every real chat including its token/usage
events, so checking the LAST few hours of Trae's own activity answers this.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
ROOT = os.path.join(APPDATA, "Trae CN")

TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
# signals that a real LLM round-trip completed
GOOD = re.compile(r"token_usage|fee_usage|\"model\"|reasoning_content|"
                  r"output_tokens|completion_tokens", re.I)
# signals a failure
BAD = re.compile(r"4011|exceeded the rate limit|2001|record not found",
                 re.I)

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    cutoff = datetime.now() - timedelta(hours=6)
    log(f"=== Trae's own chat activity since {cutoff:%Y-%m-%d %H:%M} ===")
    hits_good: list[tuple[str, str]] = []
    hits_bad: list[tuple[str, str]] = []
    latest = ""

    for base, _d, fs in os.walk(os.path.join(ROOT, "logs")):
        for fn in fs:
            p = os.path.join(base, fn)
            if not fn.lower().endswith((".log", ".txt")):
                continue
            try:
                if os.path.getsize(p) > 250 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    if b"\x00" in f.read(4096):
                        continue
                with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                    for ln in f:
                        m = TS.match(ln)
                        if not m:
                            continue
                        try:
                            dt = datetime.strptime(m.group(1),
                                                   "%Y-%m-%dT%H:%M:%S")
                        except ValueError:
                            continue
                        if dt < cutoff:
                            continue
                        latest = max(latest, m.group(1))
                        rel = p.replace(ROOT, "")
                        if BAD.search(ln):
                            hits_bad.append((m.group(1), ln.rstrip()[:300]))
                        elif GOOD.search(ln):
                            hits_good.append((m.group(1), ln.rstrip()[:300]))
            except Exception:  # noqa: BLE001
                continue

    log(f"newest log line seen: {latest or '(none in window)'}")
    log(f"\n--- successful LLM activity lines: {len(hits_good)} ---")
    for t, ln in sorted(hits_good, reverse=True)[:8]:
        log(f"  [{t}] {ln[:260]}")
    log(f"\n--- failure lines: {len(hits_bad)} ---")
    for t, ln in sorted(hits_bad, reverse=True)[:8]:
        log(f"  [{t}] {ln[:260]}")

    log("\n=== verdict ===")
    if hits_good and not hits_bad:
        log("  B: Trae itself completed real LLM calls recently -> the")
        log("     account works; our synthetic request is missing something.")
    elif hits_bad and not hits_good:
        log("  A: even Trae hit rate-limit errors -> account-wide throttle.")
    elif hits_good and hits_bad:
        log("  mixed: both seen, check which dominates / is most recent.")
    else:
        log("  (no chat activity in window - Trae may be idle; inconclusive)")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_livethrottle.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
