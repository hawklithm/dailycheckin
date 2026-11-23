"""Probe the pay/entitlement endpoints to tell real quota from throttling.

llm_raw_chat now answers 4011 "requests have exceeded the rate limit" with the
legacy header set, reproducibly, before any model is chosen. Two very
different causes fit that symptom:

  A. genuine quota exhaustion  -> must wait for the account window to reset
  B. risk-control throttling triggered by missing/odd credentials
     -> fixable by adding whatever identity field the server wants

The Trae client itself calls /api/v2/pay/ide_user_ent_usage and
/api/v2/pay/ide_user_pay_status constantly (1474 / 505 hits in the plaintext
logs), so those answers separate the two cases.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import uuid
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402

OUT: list[str] = []

HOSTS = ["https://api.trae.cn", "https://api.trae.com.cn",
         "https://trae-api-cn.mchost.guru"]

# The client's own main.log records the real URLs; note the /trae prefix that
# is easy to miss (this is why the first attempt 404'd):
#   ttnet fetch request https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage
#   ttnet fetch response .../trae/api/v2/pay/ide_user_ent_usage 200 OK
PREFIXES = ["", "/trae"]


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


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


def brief(t: str, n: int = 500) -> str:
    return " ".join(t.split())[:n]


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    jwt = auth.get_jwt()
    H = legacy(jwt, auth.creds.region)

    paths = ["/api/v2/pay/ide_user_pay_status",
             "/api/v2/pay/ide_user_ent_usage",
             "/api/v2/pay/user_current_entitlement_list",
             "/api/v2/ug/checkin_credits/status"]

    log("=== pay / entitlement status per host ===")
    found = []
    for host in HOSTS:
        for p in paths:
            for pre in PREFIXES:
                url = f"{host}{pre}{p}"
                try:
                    async with httpx.AsyncClient(timeout=30) as c:
                        r = await c.post(url, json={}, headers=H)
                except Exception as e:  # noqa: BLE001
                    log(f"  ERR {url} {e}")
                    continue
                if r.status_code == 404:
                    continue
                snippet = brief(r.text, 900)
                log(f"\n  [POST] {url} -> {r.status_code}")
                log(f"    {snippet}")
                if r.status_code == 200:
                    found.append((url, snippet))

    if not found:
        log("\n  !! no pay endpoint answered 200 on any host")

    log("\n=== interpretation ===")
    if found:
        log("  got account data above - check the payload for a remaining")
        log("  quota / balance field to tell real exhaustion from throttling")
    else:
        log("  inconclusive: pay endpoints not reachable from here")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_quota.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
