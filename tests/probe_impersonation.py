"""Why doesn't perfect impersonation work? Test the competing explanations.

User's premise: if we look exactly like the client, the server must treat us as
the client, so the block cannot be identity-based.

Competing hypotheses for the 4011 on api/agent/v3/*:

  H1 IDENTITY   - the server can tell we are not the real client.
  H2 ENDPOINT   - that endpoint family is gated regardless of who asks.
  H3 SESSION    - the server requires real server-side session state.
  H4 HANDSHAKE  - a preceding call (connect) issues a token we lack.

A clean discriminator for H1 vs H2 exists already: if identity were the gate,
then EVERY request from us would fail the same way. But we know v1/chat streams
real tokens with the same credentials, headers and account. And we know
agent_type=solo_agent itself is fine on v1/chat. So the block cannot be "you are
not the client".

This script gathers the remaining evidence for H3/H4:
  * does the real client ever call api/agent/v3/* at all? (logs)
  * what does api/ide/v1/connect do, and does it mint a session token?
  * is there a chat-level connect/session handshake we have skipped?
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import uuid
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
TRAE_LOGS = os.path.join(APPDATA, "Trae CN", "logs")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(t: str, n: int = 300) -> str:
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
        "Accept": "text/event-stream",
    }


def scan_logs() -> None:
    """Does the real client ever hit api/agent/v3/* ?"""
    log("=== does the REAL client call api/agent/v3/* ? ===")
    pats = {
        "agent/v3": re.compile(r"agent/v3"),
        "create_agent_task": re.compile(r"create_agent_task"),
        "llm_utils_chat": re.compile(r"llm_utils_chat"),
        "subscribe_events": re.compile(r"subscribe_events"),
        "start_chat": re.compile(r"start_chat"),
        "api/ide/v1/chat": re.compile(r"api/ide/v1/chat"),
        "connect": re.compile(r"api/ide/v1/connect"),
    }
    counts = {k: 0 for k in pats}
    samples: dict[str, list[str]] = {k: [] for k in pats}
    files = 0
    for base, _d, fs in os.walk(TRAE_LOGS):
        for fn in fs:
            if not fn.lower().endswith((".log", ".txt")):
                continue
            p = os.path.join(base, fn)
            try:
                if os.path.getsize(p) > 250 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    if b"\x00" in f.read(4096):
                        continue
                with io.open(p, "r", encoding="utf-8",
                             errors="replace") as f:
                    text = f.read()
            except Exception:  # noqa: BLE001
                continue
            files += 1
            for k, pat in pats.items():
                for m in pat.finditer(text):
                    counts[k] += 1
                    if len(samples[k]) < 2:
                        s = max(0, m.start() - 120)
                        samples[k].append(
                            " ".join(text[s:m.start() + 160].split())[:280])
    log(f"  scanned {files} plaintext log files")
    for k in pats:
        log(f"\n  {k:20} x{counts[k]}")
        for s in samples[k]:
            log(f"      {s}")


async def probe_connect() -> None:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)

    async def post(path, body, timeout=45):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    log("\n=== api/ide/v1/connect: does it mint a session token? ===")
    for body in ({}, {"device_id": "4333646823299987"},
                 {"user_id": auth.creds.user_id},
                 {"user_id": auth.creds.user_id,
                  "device_id": "4333646823299987"}):
        code, txt = await post("/api/ide/v1/connect", body)
        log(f"  body={brief(json.dumps(body), 70):70} -> {code} "
            f"{brief(txt, 220)}")

    log("\n=== control A/B at the same instant ===")
    text = "Reply with one word: pong"
    sid = str(uuid.uuid4())
    v1 = {"user_input": text, "session_id": sid, "chat_history": [],
          "message_content": [{"type": "text", "text_content": text}],
          "message_id": str(uuid.uuid4()),
          "agent_type": "solo_agent", "scene_location": 2,
          "agent": {"type": "solo_agent", "name": "solo_agent",
                    "title": "SOLO Agent"}}
    code, txt = await post("/api/ide/v1/chat", v1, timeout=120)
    log(f"  v1/chat agent_type=solo_agent -> {code} "
        f"{'STREAM OK' if 'token_usage' in txt else brief(txt, 120)}")

    lu = {"user_input": text, "conversation_id": sid, "session_id": sid,
          "user_id": auth.creds.user_id,
          "device_id": "4333646823299987", "ide_version": "1.107.1",
          "function": "solo_agent"}
    code, txt = await post("/api/agent/v3/llm_utils_chat", lu, timeout=90)
    kind = ("STREAM OK" if "token_usage" in txt
            else ("4011" if "exceeded the rate limit" in txt
                  else brief(txt, 120)))
    log(f"  agent/v3 llm_utils_chat fn=solo_agent -> {code} {kind}")
    log("\n  -> same account, same headers, same moment, same function name.")
    log("     If this were identity-based, BOTH would fail.")


import json  # noqa: E402


def main() -> int:
    scan_logs()
    asyncio.run(probe_connect())
    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_why_not_impersonate.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
