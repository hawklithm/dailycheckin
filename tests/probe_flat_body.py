"""Try llm_raw_chat with a FLAT body, exactly like the V1 body that works.

Key asymmetry spotted in build_chat_body: the working /api/ide/v1/chat body is
flat - user_input, message_content, model_name, agent_type, session_id, etc -
with NO service/method/user_info/common_params/client_info envelope. Every
previous llm_raw_chat probe wrapped its body in that RPC envelope (copied from
convertReqToRustPayload, which describes renderer->sidecar mojo, i.e. a
different hop than sidecar->HTTP).

So: send the proven-flat V1 body to llm_raw_chat with legacy headers, then
vary one thing at a time.
"""
from __future__ import annotations

import asyncio
import io
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


def brief(t: str, n: int = 240) -> str:
    return " ".join(t.split())[:n]


def verdict(txt: str) -> str:
    for k in ("2001", "4011", "4001", "4023"):
        if k in txt:
            return k
    if "token_usage" in txt or '"response"' in txt or "reasoning_content" in txt:
        return "STREAM!"
    return "other"


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    H = legacy(auth.get_jwt(), auth.creds.region)

    async def post(path, body, timeout=90):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{gw.base}{path}", json=body, headers=H)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            return 0, f"ERR {e}"

    sid = str(uuid.uuid4())
    flat = {
        "user_input": "Reply with one word: pong",
        "session_id": sid,
        "message_content": [{"type": "text",
                             "text_content": "Reply with one word: pong"}],
        "message_id": str(uuid.uuid4()),
        "model_name": "deepseek-v4.1-flash",
        "agent_type": "builder",
        "scene_location": 2,
        "agent": {"type": "builder", "name": "builder", "title": "Builder"},
    }

    log("=== 0. control: V1 with the flat body (known good) ===")
    code, txt = await post("/api/ide/v1/chat", {
        "user_input": flat["user_input"], "session_id": sid,
        "chat_history": [],
        "agent_type": "builder", "scene_location": 2,
        "agent": flat["agent"],
        "message_content": flat["message_content"],
        "message_id": flat["message_id"]})
    log(f"  V1 /chat            -> {code} [{verdict(txt)}] {brief(txt, 150)}")

    log("\n=== 1. same flat body against llm_raw_chat ===")
    for path in ("/api/ide/v2/llm_raw_chat", "/api/ide/v1/llm_raw_chat"):
        code, txt = await post(path, flat)
        v = verdict(txt)
        flag = "   <== CHANGED" if v != "4011" else ""
        log(f"  {path:30} -> {code} [{v}] {brief(txt, 180)}{flag}")

    log("\n=== 2. agent_type variants on flat v2 body ===")
    for at, scene in (("solo_agent", 2), ("chat", 1), ("builder", 2),
                      (None, None)):
        b = dict(flat)
        if at:
            b["agent_type"] = at
            b["agent"] = {"type": at, "name": at, "title": at}
        else:
            b.pop("agent_type", None)
            b.pop("agent", None)
        if scene:
            b["scene_location"] = scene
        code, txt = await post("/api/ide/v2/llm_raw_chat", b)
        v = verdict(txt)
        flag = "   <== CHANGED" if v != "4011" else ""
        log(f"  agent_type={str(at):12} -> [{v}] {brief(txt, 150)}{flag}")

    log("\n=== 3. minimal flat bodies ===")
    variants = [
        ("just user_input", {"user_input": "hi"}),
        ("user_input+session", {"user_input": "hi",
                                "session_id": str(uuid.uuid4())}),
        ("user_input+model", {"user_input": "hi",
                              "model_name": "deepseek-v4.1-flash"}),
        ("no model_name", {k: v for k, v in flat.items()
                           if k != "model_name"}),
    ]
    for label, b in variants:
        code, txt = await post("/api/ide/v2/llm_raw_chat", b)
        v = verdict(txt)
        flag = "   <== CHANGED" if v != "4011" else ""
        log(f"  {label:22} -> [{v}] {brief(txt, 150)}{flag}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_flatbody.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
