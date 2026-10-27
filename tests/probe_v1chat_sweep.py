"""api/v1/chat/* 404'd - but the host is confirmed correct. Find the right shape.

Confirmed from cue-server's own log:
    [DynamicDomain] applyBootConfig:
        cue={"domain":"https://trae-api-cn.mchost.guru",
             "appId":"6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"}
    [DynamicDomain] updated domain to: https://trae-api-cn.mchost.guru

So the ai-server ("cue") talks to EXACTLY the host we already use, with the
SAME appId. That means api/v1/chat/* must exist there - my earlier 404s must be
wrong in METHOD or in how the path is assembled.

Possibilities:
  * the base path already includes a prefix (e.g. /trae, /cue, /agent)
  * it is POST but requires a real body (404 vs 400 distinction)
  * it uses a different verb (PUT)
  * the path is under a service prefix like /api/v1/cue/chat/...

This probes method x prefix x path systematically and reports anything that is
not 404.
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
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []
HOST = "https://trae-api-cn.mchost.guru"
PREFIXES = ["", "/trae", "/cue", "/agent", "/api", "/v1", "/harness",
            "/trae/api", "/saas", "/copilot"]
TAILS = ["/api/v1/chat/start_chat", "/api/v1/chat/initialize",
         "/api/v1/chat/subscribe_events", "/api/v1/session/pre_terminate",
         "/api/agent/v3/create_agent_task"]
METHODS = ["POST", "PUT", "GET"]


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
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)
    H["Accept"] = "text/event-stream"

    log("=== method x prefix x path sweep (non-404 only) ===")
    hits = 0
    async with httpx.AsyncClient(timeout=20) as c:
        for tail in TAILS:
            for pre in PREFIXES:
                url = f"{HOST}{pre}{tail}"
                for method in METHODS:
                    try:
                        r = await c.request(method, url, json={},
                                            headers=H)
                    except Exception:  # noqa: BLE001
                        continue
                    if r.status_code == 404:
                        continue
                    hits += 1
                    log(f"\n  [{r.status_code}] {method:4} {url}")
                    log(f"      {brief(r.text, 260)}")
                    if hits > 40:
                        break
                if hits > 40:
                    break
            if hits > 40:
                break
    if hits == 0:
        log("  (everything 404s)")

    log("\n=== control: known-good routes on the same host ===")
    async with httpx.AsyncClient(timeout=30) as c:
        for p in ("/api/ide/v1/ping", "/api/ide/v1/chat",
                  "/api/agent/v3/create_agent_task"):
            try:
                r = await c.post(f"{HOST}{p}", json={}, headers=H)
                log(f"  {p:38} -> {r.status_code} {brief(r.text, 120)}")
            except Exception as e:  # noqa: BLE001
                log(f"  {p:38} -> ERR {e}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_v1chat_sweep.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
