"""Combine V1's working identity headers into the llm_raw_chat request.

probe_diff_v1_success isolated exactly four divergent headers between the V1
request that streams tokens and our llm_raw_chat request that answers 4011:

    X-Device-Id       missing in V1
    X-Machine-Id      missing in V1
    X-Os-Version      "10" in V1, "Windows 10 Education" in ours
    X-Trae-Client-Type  "ide" in V1, absent in ours

Note V1 headers alone give 4001 (param invalid) and legacy alone give 4011.
Neither set works, so try the union and the interesting subsets: maybe V1 is
missing the device ids (hence 4001) while we are missing X-Trae-Client-Type /
the right X-Os-Version (hence 4011).
"""
from __future__ import annotations

import asyncio
import io
import itertools
import os
import sys
import uuid
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def base(jwt, region):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Cloud-IDE-JWT {jwt}",
        "Accept": "text/event-stream",
        "X-App-Id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
        "x-plugin-channel": "icube-ai",
        "x-ide-version-code": "20260212",
        "x-ide-token": jwt,
        "X-Device-Cpu": "AMD",
        "X-Device-Brand": "MS-7B89",
        "X-Device-Type": "windows",
        "X-User-Region": region or "CN",
    }


def brief(t: str, n: int = 170) -> str:
    return " ".join(t.split())[:n]


def verdict(txt: str) -> str:
    for k in ("2001", "4011", "4001", "4023"):
        if k in txt:
            return k
    if "token_usage" in txt or '"response"' in txt:
        return "STREAM!"
    return "other"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    jwt = auth.get_jwt()

    sid = str(uuid.uuid4())
    text = "Reply with one word: pong"
    body = {"user_input": text, "session_id": sid, "chat_history": [],
            "message_content": [{"type": "text", "text_content": text}],
            "message_id": str(uuid.uuid4()),
            "model_name": "deepseek-v4.1-flash",
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder",
                      "title": "Builder"}}

    async def post(path, body_, headers, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body_,
                                 headers=headers)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    # the four knobs
    KNOBS = {
        "devid": {"X-Device-Id": "4333646823299987"},
        "machid": {"X-Machine-Id":
                   "56cb66e60ecd32141cfe256f4e5ff76e7f8d53bc99c6a93f8ef48b7cb0068524"},
        "osver10": {"X-Os-Version": "10"},
        "tcctype": {"X-Trae-Client-Type": "ide"},
    }

    log("=== single-knob and full-combination sweep on v2/llm_raw_chat ===")
    results = {}
    names = list(KNOBS)
    for r in range(0, len(names) + 1):
        for combo in itertools.combinations(names, r):
            H = base(jwt, auth.creds.region)
            for n in combo:
                H.update(KNOBS[n])
            code, txt = await post("/api/ide/v2/llm_raw_chat", body, H)
            v = verdict(txt)
            label = "+".join(combo) or "(none)"
            results[label] = v
            flag = "   <== CHANGED" if v not in ("4011", "4001") else ""
            log(f"  {label:34} -> [{v:7}] {brief(txt, 110)}{flag}")

    log("\n=== sweep summary ===")
    from collections import Counter
    c = Counter(results.values())
    for k, n in c.most_common():
        log(f"    {k:8} x{n}")
    for label, v in results.items():
        if v not in ("4011", "4001"):
            log(f"  WINNER: {label} -> {v}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_hdrunion.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
