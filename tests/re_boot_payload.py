"""Capture the boot-config payload that carries cloud_url.

harness.dll references:
    harness\\server\\src\\config\\boot.rs   "set HARNESS_CLOUD_URL or provide
        agent.domain in boot-config"
    harness\\server\\src\\startup\\run_support.rs  "updated shared Cloud API
        config from boot-config", fields: boot_config_version, cloud_url
    struct: appId, httpDNS, netLog, tncHost, userId, tenantId, loginScope,
            isI18nPackage   (this is the cloud-api config struct)

The client fetches boot config over the aha IPC channel
"trae-cn-config-channel" (cue-server log). The payload is delivered at runtime
and may be visible in:
  * cue-server stdout/stderr logs (it logs BootService calls)
  * main.log around "BootConfig success"
  * a local cache file

This scans ALL Trae logs for the cloud URL / boot payload, including the
cue-server logs we have not fully read.
"""
from __future__ import annotations

import io
import os
import re
import sys

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
TRAE = os.path.join(APPDATA, "Trae CN")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    log("=" * 74)
    log("A. every cue-server / modular stdout log")
    log("=" * 74)
    n = 0
    for base, _d, fs in os.walk(os.path.join(TRAE, "logs")):
        for fn in fs:
            low = fn.lower()
            if not low.endswith((".log", ".txt")):
                continue
            if not any(k in low for k in ("cue", "stdout", "harness",
                                          "agent")):
                continue
            p = os.path.join(base, fn)
            try:
                if os.path.getsize(p) > 100 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    head = f.read(4096)
                if b"\x00" in head:
                    continue
                with io.open(p, "r", encoding="utf-8",
                             errors="replace") as f:
                    text = f.read()
            except Exception:  # noqa: BLE001
                continue
            log(f"\n  ### {p.replace(TRAE, '')}  ({len(text)} chars)")
            # look for url-ish and config-ish lines
            for line in text.splitlines():
                low_line = line.lower()
                if any(k in low_line for k in
                       ("cloud", "domain", "bootconfig", "boot config",
                        "agent", "endpoint", "baseurl", "base_url",
                        "http://", "https://")):
                    s = " ".join(line.split())
                    if len(s) > 4:
                        log("      " + s[:300])
                        n += 1
                        if n > 200:
                            break
            if n > 200:
                break
        if n > 200:
            break
    if n == 0:
        log("  (nothing)")

    log("\n" + "=" * 74)
    log("B. search ALL logs for a cloud_url-looking assignment")
    log("=" * 74)
    pat = re.compile(
        r"(cloud[_-]?url|agent\.domain|HARNESS_CLOUD_URL|baseUrl|base_url)"
        r"[^\n]{0,200}", re.I)
    seen = 0
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
            for m in pat.finditer(text):
                if seen >= 25:
                    break
                log("  [" + os.path.basename(p) + "] "
                    + " ".join(m.group(0).split())[:260])
                seen += 1
    if seen == 0:
        log("  (none)")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_bootpayload.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:14000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
