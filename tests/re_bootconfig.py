"""Find the actual agent.domain / boot-config values.

harness.dll says:
    set HARNESS_CLOUD_URL or provide agent.domain in boot-config
    set HARNESS_COPILOT_APP_ID, COPILOT_APP_ID, or provide agent.appId in boot-config

So ai-server needs a CLOUD URL that comes from boot-config, delivered over
aha_ipc ("[AhaIPCSource] start_boot_config_stream",
"event:BootService.onDidBootConfigChanged").

Where does boot-config live? Sources to check:
  * local cache files (json) under %APPDATA%\Trae CN
  * the boot service response, possibly in logs
  * ahanet/server.json (already found, holds api hosts)

Let's search all local JSON/config for agent domain + appId keys, and search
logs for the boot-config payload.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
TRAE = os.path.join(APPDATA, "Trae CN")

OUT: list[str] = []

KEYS = ("agent.domain", "agent.appId", "agent_domain", "agent_app_id",
        "cloud_url", "cloudUrl", "HARNESS_CLOUD_URL", "COPILOT_APP_ID",
        "agentDomain", "agentAppId", "domain")


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def walk_json(obj, pre="", depth=0):
    """Yield (path, value) for agent-ish keys."""
    if depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{pre}.{k}" if pre else k
            kl = k.lower()
            if any(t in kl for t in ("agent", "domain", "cloud", "copilot",
                                     "appid", "app_id", "boot")):
                if not isinstance(v, (dict, list)):
                    yield p, v
                else:
                    yield p, f"<{type(v).__name__} len {len(v)}>"
            yield from walk_json(v, p, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:8]):
            yield from walk_json(v, f"{pre}[{i}]", depth + 1)


def main() -> int:
    log("=" * 74)
    log("A. agent-ish keys in every local JSON under %APPDATA%\\Trae CN")
    log("=" * 74)
    n = 0
    for base, _d, fs in os.walk(TRAE):
        for fn in fs:
            if not fn.lower().endswith((".json", ".json5")):
                continue
            p = os.path.join(base, fn)
            try:
                if os.path.getsize(p) > 16 * 1024 * 1024:
                    continue
                with io.open(p, encoding="utf-8", errors="replace") as f:
                    obj = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            rows = list(walk_json(obj))
            if not rows:
                continue
            rel = p.replace(TRAE, "")
            log(f"\n  ### {rel}")
            for k, v in rows[:25]:
                s = str(v)
                if len(s) > 140:
                    s = s[:140] + "..."
                log(f"      {k} = {s}")
            n += 1
            if n >= 14:
                break
        if n >= 14:
            break
    if n == 0:
        log("  (no agent-ish keys in local JSON)")

    log("\n" + "=" * 74)
    log("B. boot-config payload in logs")
    log("=" * 74)
    pats = [re.compile(r"boot.?config[^\n]{0,400}", re.I),
            re.compile(r'"agent"\s*:\s*\{[^}]{0,400}', re.I),
            re.compile(r'agent\.domain[^\n]{0,200}', re.I),
            re.compile(r'HARNESS_CLOUD_URL[^\n]{0,200}', re.I)]
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
                    if hits >= 15:
                        break
                    s = " ".join(m.group(0).split())[:350]
                    if "boot config from boot service" in s and len(s) < 60:
                        continue
                    log(f"  [{os.path.basename(p)}] {s}")
                    hits += 1
    if hits == 0:
        log("  (none)")

    log("\n" + "=" * 74)
    log("C. ahanet/server.json content (hosts + ttnet config)")
    log("=" * 74)
    p = os.path.join(TRAE, "ahanet", "server.json")
    if os.path.exists(p):
        try:
            with io.open(p, encoding="utf-8", errors="replace") as f:
                obj = json.load(f)
            log(json.dumps(obj, indent=2, ensure_ascii=False)[:4000])
        except Exception as e:  # noqa: BLE001
            log(f"  parse failed: {e}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_bootconfig.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:14000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
