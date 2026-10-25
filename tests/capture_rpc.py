"""Capture Trae's local sidecar RPC while the user chats in Trae.

Why this exists
---------------
The real Trae path is: renderer -> local sidecar (ai_agent.dll) -> LLM
provider. The sidecar only binds a local port while an AI conversation is
active, so this script waits for that port to appear, then connects to the
UnifiedTransport WebSocket endpoint (/ws) and records every frame.

ai_agent.dll strings prove the shape:
  src/infrastructure/transport/unified.rs
  "/ws"  "/api/v1/:service/:method"  "127.0.0.1"
  "[UnifiedTransport] server listening on: ?"
  "[UnifiedTransport] text message: service=?, method=?, user=?"

Usage
-----
  python tests/capture_rpc.py            # watch until the port appears
  python tests/capture_rpc.py --port N   # skip discovery, connect directly
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import io
import json
import os
import socket
import sys
import time

import websockets

LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
MAX_SECONDS = float(os.environ.get("CAPTURE_SECONDS", "600"))


def log(fh, msg: str) -> None:
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def trae_pids() -> set[int]:
    """PIDs of running Trae processes (via PowerShell, no extra deps)."""
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process -Name 'Trae CN' -ErrorAction SilentlyContinue).Id"],
            capture_output=True, text=True, timeout=20).stdout
        return {int(x) for x in out.split() if x.strip().isdigit()}
    except Exception:
        return set()


def listening_ports(pids: set[int]) -> list[int]:
    """Loopback TCP listeners owned by Trae."""
    try:
        import subprocess
        ps = (
            "$p = @(" + ",".join(str(p) for p in pids) + "); "
            "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
            "Where-Object { $_.OwningProcess -in $p -and "
            "$_.LocalAddress -match '127\\.0\\.0\\.1|::1|0\\.0\\.0\\.0' } | "
            "Select-Object -ExpandProperty LocalPort"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=25).stdout
        return sorted({int(x) for x in out.split() if x.strip().isdigit()})
    except Exception:
        return []


def probe_ws(port: int, timeout: float = 2.5) -> bool:
    """Is /ws a WebSocket on this port? Try an upgrade and read any bytes."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except Exception:
        return False
    try:
        req = (
            f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.sendall(req.encode())
        s.settimeout(timeout)
        data = s.recv(4096)
        return b"101" in data[:32]
    except Exception:
        return False
    finally:
        s.close()


async def capture(port: int, fh, path: str = "/ws") -> int:
    url = f"ws://127.0.0.1:{port}{path}"
    log(fh, f"connecting {url}")
    frames = 0
    try:
        async with websockets.connect(url, open_timeout=8, max_size=None) as ws:
            log(fh, "connected - send a message in Trae now")
            deadline = time.time() + MAX_SECONDS
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    log(fh, f"closed: {e}")
                    break
                frames += 1
                if isinstance(msg, bytes):
                    fh.write(f"--- frame {frames} BINARY len={len(msg)}\n")
                    fh.write(msg[:4000].hex() + "\n")
                else:
                    fh.write(f"--- frame {frames} TEXT len={len(msg)}\n")
                    fh.write(msg[:8000] + "\n")
                fh.flush()
                log(fh, f"frame {frames} ({len(msg)} bytes)")
    except Exception as e:  # noqa: BLE001
        log(fh, f"connect failed: {type(e).__name__}: {e}")
    return frames


async def amain(args) -> int:
    os.makedirs(LOGS, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    fpath = os.path.join(LOGS, f"rpc-capture-{stamp}.txt")
    with io.open(fpath, "w", encoding="utf-8") as fh:
        log(fh, f"capture file: {fpath}")

        port = args.port
        if not port:
            log(fh, "waiting for Trae sidecar port (open Trae and start a chat)...")
            deadline = time.time() + args.discover_seconds
            seen: set[int] = set()
            while time.time() < deadline:
                pids = trae_pids()
                if pids:
                    ports = listening_ports(pids)
                    new = [p for p in ports if p not in seen]
                    for p in new:
                        seen.add(p)
                        if probe_ws(p):
                            log(fh, f"found /ws on port {p}")
                            port = p
                            break
                    if port:
                        break
                    if new:
                        log(fh, f"ports={ports} (no /ws yet)")
                await asyncio.sleep(2.0)
            if not port:
                log(fh, "no sidecar /ws port found - is Trae running with an open chat?")
                return 1

        n = await capture(port, fh, args.path)
        log(fh, f"captured {n} frames")
        return 0 if n else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--path", default="/ws")
    ap.add_argument("--discover-seconds", type=float, default=420.0)
    a = ap.parse_args()
    return asyncio.run(amain(a))


if __name__ == "__main__":
    sys.exit(main())
