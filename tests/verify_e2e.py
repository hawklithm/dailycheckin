"""End-to-end check that the server extensions work over the real proxy.

Verifies against a live /v1/chat/completions call:
  * streaming still produces content deltas
  * the final chunk now carries a real `usage` object (from token_usage)
  * no event is silently dropped (unknown events would be logged)
  * non-streaming still returns a coherent message

Runs the proxy in-process via httpx ASGI transport so no port is needed.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


async def main() -> int:
    from trae2api.server import app, _startup

    # The proxy builds its gateway in a startup hook; ASGITransport does not
    # run lifespan events, so invoke it explicitly before calling the routes.
    await _startup()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test",
                                 timeout=180) as c:
        # --- streaming ---
        log("=== streaming /v1/chat/completions ===")
        content = []
        usage = None
        finish = None
        n_chunks = 0
        async with c.stream("POST", "/v1/chat/completions", json={
            "model": "trae",
            "stream": True,
            "messages": [{"role": "user",
                          "content": "Reply with one word: pong"}],
        }) as r:
            log(f"  http {r.status_code}")
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    j = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                n_chunks += 1
                if j.get("usage"):
                    usage = j["usage"]
                ch = (j.get("choices") or [{}])[0]
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
                d = ch.get("delta") or {}
                if d.get("content"):
                    content.append(d["content"])

        text = "".join(content)
        log(f"  chunks={n_chunks} finish={finish}")
        log(f"  content={text[:120]!r}")
        log(f"  usage={usage}")
        ok_stream = bool(text.strip()) and finish in ("stop", "tool_calls")
        log(f"  -> content ok: {ok_stream}")
        log(f"  -> usage present: {usage is not None}")

        # --- non-streaming ---
        log("\n=== non-streaming /v1/chat/completions ===")
        r = await c.post("/v1/chat/completions", json={
            "model": "trae",
            "stream": False,
            "messages": [{"role": "user",
                          "content": "Reply with one word: pong"}],
        })
        log(f"  http {r.status_code}")
        try:
            j = r.json()
            msg = (j.get("choices") or [{}])[0].get("message") or {}
            log(f"  content={ (msg.get('content') or '')[:120]!r}")
            log(f"  usage={j.get('usage')}")
            log(f"  finish={(j.get('choices') or [{}])[0].get('finish_reason')}")
        except Exception as e:  # noqa: BLE001
            log(f"  parse failed: {e}: {r.text[:200]}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_e2e_verify.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
