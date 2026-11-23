"""Does the currently-shipped V1 path actually return LLM text right now?

All previous work assumed `/api/ide/v1/chat` works (handoff section 2.3).
Let's verify it end-to-end rather than trusting the note.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    msgs = [{"role": "user", "content": "Reply with the single word: pong"}]
    got = bytearray()
    try:
        async for chunk in gw.stream_chat("auto", msgs):
            got.extend(chunk)
    except Exception as e:  # noqa: BLE001
        log(f"V1 stream_chat raised: {type(e).__name__}: {e}")
        io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs", "_v1verify.txt"), "w",
            encoding="utf-8").write("\n".join(OUT))
        print("\n".join(OUT))
        return 1
    text = got.decode("utf-8", "replace")
    log(f"V1 /api/ide/v1/chat -> {len(got)} bytes")
    log("---- first 1200 chars ----")
    log(text[:1200])
    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_v1verify.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
