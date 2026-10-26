"""Separate 'model endpoint' quota from 'account credits'.

Entitlement data (probe_quota.py) shows the account is NOT exhausted:
    usage_summary: consumed 1891.89 / total 4900 (ratio 0.386) -> 61% left
    quota: credits_limit 4000, no_bonus_quota true
    available_endpoint: 0     <-- suspicious
so plain "you ran out" is wrong. The remaining candidate is that a single
model/endpoint allocation is exhausted or gated, while overall credits remain.

This probe pulls the full entitlement payload looking for per-model /
per-endpoint quotas, and checks the diagnostic signals the UI uses.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402

OUT: list[str] = []
HOST = "https://api.trae.cn"


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


def walk(obj, path="", hits=None, depth=0):
    """Surface every quota/limit/endpoint-ish leaf."""
    if hits is None:
        hits = []
    if depth > 6:
        return hits
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            interesting = any(t in kl for t in
                              ("quota", "limit", "endpoint", "available",
                               "remain", "balance", "usage", "consume",
                               "credits", "amount", "status", "expire"))
            if interesting and not isinstance(v, (dict, list)):
                hits.append((f"{path}.{k}" if path else k, v))
            walk(v, f"{path}.{k}" if path else k, hits, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:6]):
            walk(v, f"{path}[{i}]", hits, depth + 1)
    return hits


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    H = legacy(auth.get_jwt(), auth.creds.region)

    async def post(path, body=None, timeout=30):
        url = f"{HOST}/trae{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body or {}, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    for p in ("/api/v2/pay/ide_user_ent_usage",
              "/api/v2/pay/user_current_entitlement_list"):
        code, txt = await post(p)
        log(f"\n===== {p} -> {code}")
        try:
            j = json.loads(txt)
        except Exception:  # noqa: BLE001
            log("  (not json) " + txt[:300])
            continue
        top = {k: v for k, v in j.items() if not isinstance(v, (dict, list))}
        log("  top-level: " + json.dumps(top, ensure_ascii=False))
        for name, val in walk(j):
            log(f"    {name:64} = {val}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_entdetail.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
