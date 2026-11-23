"""Find what the real client knows about quota / limits in its plaintext logs.

The pay endpoints are not reachable from our own calls, but the Trae client
queries them constantly (ide_user_ent_usage x1474 etc.) and sometimes logs the
response payloads. Those recorded answers tell us whether the account is
genuinely out of quota, and reveal other error codes the server emits.
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
ROOT = os.path.join(APPDATA, "Trae CN")

PATTERNS = {
    "4011": re.compile(r"\b4011\b"),
    "quota_exceeded": re.compile(r"exceeded the rate limit|quota", re.I),
    "pay_status": re.compile(r"ide_user_pay_status|payStatus|pay_status", re.I),
    "ent_usage": re.compile(r"ide_user_ent_usage|ent_usage|entitlement", re.I),
    "credits": re.compile(r"checkin_credits|credits_balance|remaining", re.I),
}

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    counts: Counter = Counter()
    samples: dict[str, list[tuple[str, str]]] = {}

    for base, _d, fs in os.walk(ROOT):
        for fn in fs:
            p = os.path.join(base, fn)
            if not fn.lower().endswith((".log", ".txt", ".json")):
                continue
            try:
                if os.path.getsize(p) > 250 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    if b"\x00" in f.read(4096):
                        continue
                with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                    for ln in f:
                        for name, pat in PATTERNS.items():
                            if pat.search(ln):
                                counts[name] += 1
                                samples.setdefault(name, [])
                                if len(samples[name]) < 4:
                                    rel = p.replace(ROOT, "")
                                    samples[name].append(
                                        (rel, ln.rstrip("\n")[:900]))
            except Exception:  # noqa: BLE001
                continue

    log("=== keyword counts in plaintext Trae logs ===")
    for k, v in counts.most_common():
        log(f"    {k:16} x{v}")

    for name in PATTERNS:
        if name not in samples:
            continue
        log(f"\n=== {name} ===")
        for rel, ln in samples[name]:
            log(f"  [{rel}]")
            log(f"    {ln}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_quotascan.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
