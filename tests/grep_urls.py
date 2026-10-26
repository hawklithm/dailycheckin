"""Enumerate every URL / app_id the Trae client actually resolves.

`2001 failed to get app config: record not found` may simply mean we are
talking to the wrong server (or the wrong app_id) for the config lookup. The
client logs "[ApiManager] resolved url for <path>: <full url>" in plaintext,
so we can list exactly which paths exist and on which host.
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
ROOT = os.path.join(APPDATA, "Trae CN")

URL_RE = re.compile(r"resolved url for\s+([^\s:]+)\s*:\s*(\S+)")
HOST_RE = re.compile(r"https?://([A-Za-z0-9._-]+)")
APPID_RE = re.compile(r'"app_id"\s*:\s*"([^"]+)"')
PATHS_RE = re.compile(r"(/api/[A-Za-z0-9._/-]+)")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    paths: Counter = Counter()
    hosts: Counter = Counter()
    appids: Counter = Counter()
    apipaths: Counter = Counter()

    for base, _d, fs in os.walk(ROOT):
        for fn in fs:
            p = os.path.join(base, fn)
            if not fn.lower().endswith((".log", ".txt", ".json", ".js")):
                continue
            try:
                if os.path.getsize(p) > 250 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    if b"\x00" in f.read(4096):
                        continue
                with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except Exception:  # noqa: BLE001
                continue
            for m in URL_RE.finditer(text):
                paths[m.group(1)] += 1
                h = HOST_RE.match(m.group(2))
                if h:
                    hosts[h.group(1)] += 1
            for m in APPID_RE.finditer(text):
                appids[m.group(1)] += 1
            for m in PATHS_RE.finditer(text):
                apipaths[m.group(1)] += 1

    log("=== hosts the client talks to ===")
    for h, c in hosts.most_common(20):
        log(f"    {h:44} x{c}")

    log("\n=== 'resolved url for <path>' (ApiManager) ===")
    for pa, c in paths.most_common(60):
        log(f"    {pa:60} x{c}")

    log("\n=== app_id values ===")
    for a, c in appids.most_common(20):
        log(f"    {a:44} x{c}")

    log("\n=== all /api/... paths seen anywhere in plaintext ===")
    skip = ("v1/code_completion",)
    for pa, c in apipaths.most_common(120):
        if any(s in pa for s in skip) and c < 3:
            continue
        log(f"    {pa:70} x{c}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_urls.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
