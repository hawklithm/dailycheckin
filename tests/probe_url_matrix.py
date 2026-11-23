"""Find the right URL prefix for api/v1/chat/*.

All 9 routes 404'd at {gateway}/api/v1/chat/*. But the host is resolved at
runtime by TTNet httpDNS, and we KNOW /trae was the missing prefix for the
pay endpoints (https://api.trae.cn/trae/api/v2/pay/...). The same trick may
apply here, and on several candidate hosts.

Test matrix: {host} x {prefix} x {route}
    hosts:   trae-api-cn.mchost.guru, api.trae.cn, api.trae.com.cn
    prefixes: "", "/trae"
    routes:  api/v1/chat/initialize, api/agent/v3/create_agent_task, ...

Report only non-404 results.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402

OUT: list[str] = []

HOSTS = ["https://trae-api-cn.mchost.guru", "https://api.trae.cn",
         "https://api.trae.com.cn"]
PREFIXES = ["", "/trae"]
ROUTES = ["/api/v1/chat/initialize", "/api/v1/chat/start_chat",
          "/api/v1/chat/subscribe_events", "/api/agent/v3/create_agent_task",
          "/api/v1/session/pre_terminate", "/api/v1/goal/get"]


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 200) -> str:
    return " ".join(t.split())[:n]


def legacy(jwt, region):
    return {
        "X-App-Id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
        "x-plugin-channel": "icube-ai",
        "x-ide-version-code": "20260212",
        "x-ide-token": jwt,
        "Content-Type": "application/json",
        "Authorization": f"Cloud-IDE-JWT {jwt}",
        "X-Device-Cpu": "AMD",
        "X-Device-Id": "4333646823299987",
        "X-Machine-Id": "56cb66e60ecd32141cfe256f4e5ff76e7f8d53bc99c6a93f8ef48b7cb0068524",
        "X-Device-Brand": "MS-7B89",
        "X-Device-Type": "windows",
        "X-Os-Version": quote("Windows 10 Education"),
        "X-User-Region": region or "CN",
    }


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    H = legacy(auth.get_jwt(), auth.creds.region)

    log("=== URL matrix (only non-404 reported) ===")
    hits = 0
    async with httpx.AsyncClient(timeout=25) as c:
        for host in HOSTS:
            for pre in PREFIXES:
                for route in ROUTES:
                    url = f"{host}{pre}{route}"
                    try:
                        r = await c.post(url, json={}, headers=H)
                    except Exception as e:  # noqa: BLE001
                        log(f"  ERR {url} {e}")
                        continue
                    if r.status_code == 404:
                        continue
                    hits += 1
                    log(f"\n  [{r.status_code}] {url}")
                    log(f"      {brief(r.text, 260)}")
    if not hits:
        log("  (every combination 404s)")

    log("\n=== control: does the known-good route still work? ===")
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(f"{HOSTS[0]}/api/ide/v1/ping", json={}, headers=H)
    log(f"  ping -> {r.status_code} {brief(r.text, 120)}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_urlmatrix.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
