"""Determine what content type llm_raw_chat expects.

The sidecar's HTTP transport is Rust (reqwest/tonic). If it speaks protobuf,
a JSON body will always 4001. Test: send protobuf-encoded bodies and different
content types, and see whether the error changes.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)
    hdrs = gw._headers()

    log("=== headers we send ===")
    for k, v in hdrs.items():
        vv = v if len(v) < 60 else v[:57] + "..."
        log(f"  {k}: {vv}")

    async def send(path, content, ctype, label):
        h = dict(hdrs)
        h["Content-Type"] = ctype
        try:
            async with httpx.AsyncClient(timeout=45) as c:
                r = await c.post(f"{gw.base}{path}", content=content, headers=h)
            body = r.text[:250]
            log(f"  [{label}] ctype={ctype} -> {r.status_code} {body}")
        except Exception as e:  # noqa: BLE001
            log(f"  [{label}] ctype={ctype} -> ERR {type(e).__name__}: {e}")

    # 1. empty body
    await send("/api/ide/v2/llm_raw_chat", b"", "application/json", "empty")
    await send("/api/ide/v2/llm_raw_chat", b"", "application/protobuf", "empty")
    await send("/api/ide/v2/llm_raw_chat", b"", "application/grpc", "empty")

    # 2. empty json object
    await send("/api/ide/v2/llm_raw_chat", b"{}", "application/json", "{}")

    # 3. a trivial protobuf message: field 1 (string) = "a"
    #    tag=0x0a len=1 'a'
    await send("/api/ide/v2/llm_raw_chat", b"\x0a\x01a", "application/protobuf", "pb f1=a")
    # field 1 string = "" (empty)
    await send("/api/ide/v2/llm_raw_chat", b"\x0a\x00", "application/protobuf", "pb f1=empty")
    # field 2 varint 0
    await send("/api/ide/v2/llm_raw_chat", b"\x10\x00", "application/protobuf", "pb f2=0")

    # 4. the model_list endpoint, same treatment
    for ct in ("application/json", "application/protobuf", "application/grpc"):
        await send("/api/ide/v1/model_list", b"{}", ct, "ml {}")

    # 5. maybe it's a GET
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{gw.base}/api/ide/v1/model_list", headers=hdrs)
        log(f"  [GET model_list] -> {r.status_code} {r.text[:200]}")
    except Exception as e:  # noqa: BLE001
        log(f"  [GET model_list] -> ERR {e}")

    io.open("logs/_ctype.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
