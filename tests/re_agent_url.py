"""Get the REAL agent cloud URL: what does ai-server POST to?

harness.dll says: "set HARNESS_CLOUD_URL or provide agent.domain in boot-config".
So the URL comes from boot-config at runtime. Two ways to learn it:

1. Read the boot-config the client received. cue-server's log said
   "[BootService] getBootConfig success" over channel trae-cn-config-channel.
   The payload may be cached somewhere on disk.

2. Find the request-builder in harness.dll: the code that builds the URL from
   agent.domain + a path. Strings like "{}/api/agent/v3/create_agent_task"
   would reveal the composition.

Also note cueMain.js is the OVERSEAS Marscode bundle (byteintl.net hosts), so
the CN path lives in harness.dll / ai_agent.dll, not in cueMain.js.

This searches harness.dll for URL-composition patterns and the boot-config
struct fields (agent.domain / agent.appId).
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
HARNESS = os.path.join(TRAE, r"resources\app\modules\ai-agent\harness.dll")
AGENT = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def clean(b: bytes, n: int = 1400) -> str:
    return re.sub(rb"[^\x20-\x7e]+", b" | ", b).decode("ascii", "replace")[:n]


def main() -> int:
    with io.open(HARNESS, "rb") as f:
        hb = f.read()

    log("=" * 74)
    log("A. boot-config struct: agent.* fields")
    log("=" * 74)
    # find runs containing 'agent' + 'appId' + 'domain' together
    for m in re.finditer(rb"domain", hb):
        p = m.start()
        win = hb[max(0, p - 400):p + 400]
        txt = clean(win, 800)
        if "appId" in txt or "app_id" in txt:
            log(f"\n--- @{p} ---")
            log("  " + txt)
            break

    # search for the literal field names
    for needle in (b"agentDomain", b"agent_domain", b"agentAppId",
                   b"appId", b"cloudUrl", b"cloud_url"):
        c = hb.count(needle)
        log(f"\n  {needle.decode():16} x{c}")
        if 0 < c < 60:
            p = hb.find(needle)
            log("    " + clean(hb[max(0, p - 350):p + 350], 700))

    log("\n" + "=" * 74)
    log("B. URL composition: strings ending in the agent paths")
    log("=" * 74)
    for path in (b"api/agent/v3/create_agent_task",
                 b"api/agent/v3/llm_utils_chat",
                 b"api/v1/chat/start_chat"):
        p = hb.find(path)
        if p < 0:
            continue
        # what precedes the path? format!() templates look like "{}/api/..."
        before = hb[max(0, p - 200):p]
        log(f"\n--- {path.decode()} @{p} ---")
        log("  before: " + clean(before, 400))
        log("  after : " + clean(hb[p:p + 260], 300))

    log("\n" + "=" * 74)
    log("C. HARNESS_CLOUD_URL / COPILOT_APP_ID handling")
    log("=" * 74)
    for needle in (b"HARNESS_CLOUD_URL", b"HARNESS_COPILOT_APP_ID",
                   b"COPILOT_APP_ID"):
        p = hb.find(needle)
        log(f"\n  {needle.decode()} @{p}")
        if p > 0:
            log("    " + clean(hb[max(0, p - 500):p + 600], 1100))

    log("\n" + "=" * 74)
    log("D. any hardcoded CN agent host in harness/agent dll")
    log("=" * 74)
    for path, label in ((HARNESS, "harness"), (AGENT, "ai_agent")):
        with io.open(path, "rb") as f:
            b = f.read()
        for pat in (rb"[a-z0-9-]+\.mchost\.guru",
                    rb"[a-z0-9-]+\.byteintlapi\.com",
                    rb"agent[a-z0-9.-]*\.trae[a-z0-9.-]*"):
            found = sorted({m.group(0).decode("ascii", "replace")
                            for m in re.finditer(pat, b)})
            if found:
                log(f"  [{label}] {pat.decode()[:30]}: {found[:10]}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_agent_url.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:14000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
