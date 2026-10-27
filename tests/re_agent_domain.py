"""Find the REAL host/route that serves api/v1/chat/* and the agent domain.

Earlier I tested only 3 hosts and concluded api/v1/chat/* is local. That may be
wrong: the sidecar resolves its own host at runtime via TTNet httpDNS, and
HubHandler logs "refresh boot config: agent.domain=..." - i.e. there IS a
configurable agent domain we never used.

So: find the agent domain from (a) client config files, (b) logs, (c) the DLL's
boot-config structs. Then test api/v1/chat/* against it.
"""
from __future__ import annotations

import io
import os
import re
import sys

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
TRAE = os.path.join(APPDATA, "Trae CN")
INSTALL = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
DLL = os.path.join(INSTALL, r"resources\app\modules\ai-agent\harness.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    # --- 1. agent.domain / boot config in logs ---------------------------
    log("=" * 74)
    log("A. 'agent.domain' / boot config in client logs")
    log("=" * 74)
    pats = [re.compile(r"agent\.domain[^\n]{0,200}", re.I),
            re.compile(r"boot config[^\n]{0,300}", re.I),
            re.compile(r"refresh boot config[^\n]{0,300}", re.I)]
    hits = 0
    for base, _d, fs in os.walk(os.path.join(TRAE, "logs")):
        for fn in fs:
            if not fn.lower().endswith((".log", ".txt")):
                continue
            p = os.path.join(base, fn)
            try:
                if os.path.getsize(p) > 200 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    if b"\x00" in f.read(4096):
                        continue
                with io.open(p, "r", encoding="utf-8",
                             errors="replace") as f:
                    text = f.read()
            except Exception:  # noqa: BLE001
                continue
            for pat in pats:
                for m in pat.finditer(text):
                    if hits < 12:
                        log("  " + " ".join(m.group(0).split())[:300])
                        hits += 1
    if not hits:
        log("  (none found in logs)")

    # --- 2. domain-ish config files --------------------------------------
    log("\n" + "=" * 74)
    log("B. domain config files on disk")
    log("=" * 74)
    for rel in ("ahanet/server.json", "ahanet/config.json"):
        p = os.path.join(TRAE, rel)
        if os.path.exists(p):
            log(f"  found {rel} ({os.path.getsize(p)} bytes)")
    # scan any json under Trae CN for host keys
    host_keys = ("host", "domain", "endpoint", "base_url", "server")
    found: dict[str, int] = {}
    for base, _d, fs in os.walk(TRAE):
        for fn in fs:
            if not fn.lower().endswith(".json"):
                continue
            p = os.path.join(base, fn)
            try:
                if os.path.getsize(p) > 8 * 1024 * 1024:
                    continue
                with io.open(p, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except Exception:  # noqa: BLE001
                continue
            for m in re.finditer(
                    r"https?://[a-zA-Z0-9._-]{4,60}", txt):
                u = m.group(0)
                if any(k in u.lower() for k in
                       ("trae", "mchost", "byteintl", "guru", "agent")):
                    found[u] = found.get(u, 0) + 1
    for u, c in sorted(found.items(), key=lambda kv: -kv[1])[:30]:
        log(f"    {u:58} x{c}")

    # --- 3. the boot config struct in harness.dll ------------------------
    log("\n" + "=" * 74)
    log("C. boot config fields (harness.dll)")
    log("=" * 74)
    if os.path.exists(DLL):
        with io.open(DLL, "rb") as f:
            buf = f.read()
        for needle in (b"agent.domain", b"agent_domain", b"BootConfig",
                       b"boot_config", b"domain"):
            p = buf.find(needle)
            if p < 0:
                log(f"\n  {needle.decode()}: absent")
                continue
            frag = re.sub(rb"[^\x20-\x7e]+", b" | ",
                          buf[max(0, p - 500):p + 700])
            log(f"\n  --- {needle.decode()} @{p} ---")
            log("    " + frag.decode("ascii", "replace")[:1100])

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_agent_domain.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:14000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
