"""Attempt to speak Trae's sidecar IPC (aha-ipc) over its named pipe.

aha-ipc facts extracted from ai_agent.dll:
  - payload is JSON (serde_json RawValue): "[aha_ipc] JSON parsed successfully"
  - messages are length-framed: "[aha_ipc] ServerConnectionWriter::write called,
    message len=", "[aha_ipc] received <n> bytes from connection"
  - envelope type: aha_ipc::rpc::RpcMessage, field set "FieldSet"
  - RPC shape from workbench TransportManager: {service, method, ...}

The pipe is single-instance, so we open once with pywin32 and use a reader
thread. Five candidate framings are tried in sequence; the first that yields a
well-formed reply wins.
"""
from __future__ import annotations

import io
import json
import os
import struct
import sys
import threading
import time

import pywintypes
import win32file
import win32pipe

LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


def sidecar_pids() -> list[int]:
    import subprocess
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like '%Trae%'\" | "
          "Where-Object { $_.CommandLine -match 'process-type=ai' } | "
          "ForEach-Object { $_.ProcessId }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=25).stdout
    return [int(x) for x in out.split() if x.strip().isdigit()]


def find_pipe(pids: list[int]) -> str | None:
    names = os.listdir(r"\\.\pipe\\")
    for n in names:
        if n.startswith("agent-code-toolhost-"):
            for p in pids:
                if f"-{p}-" in n:
                    return "\\\\.\\pipe\\" + n
    for n in names:
        if n.startswith("agent-code-toolhost-"):
            return "\\\\.\\pipe\\" + n
    return None


def frame_candidates(payload: dict) -> list[tuple[str, bytes]]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    return [
        ("u32le+json", struct.pack("<I", len(body)) + body),
        ("u32be+json", struct.pack(">I", len(body)) + body),
        ("u64le+json", struct.pack("<Q", len(body)) + body),
        ("json+\\n", body + b"\n"),
        ("json", body),
    ]


def try_pipe(pipe: str) -> None:
    log(f"pipe: {pipe}")

    # envelope guesses, most specific first
    reqs = [
        {"service": "lite", "method": "agent_ready", "data": {}},
        {"type": "request", "service": "lite", "method": "agent_ready", "data": {}},
        {"request": {"service": "lite", "method": "agent_ready"}, "data": {}},
    ]

    for req in reqs:
        log(f"\n=== request: {json.dumps(req, ensure_ascii=False)}")
        for label, blob in frame_candidates(req):
            try:
                h = win32file.CreateFile(
                    pipe,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None)
            except pywintypes.error as e:
                log(f"  [{label}] open failed: {e.args}")
                return  # pipe refuses further connections

            got: dict = {}

            def reader(handle=h):
                try:
                    got["data"] = win32file.ReadFile(handle, 65536)
                except pywintypes.error as e:
                    got["err"] = e.args

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            try:
                win32file.WriteFile(h, blob)
                log(f"  [{label}] sent {len(blob)}B")
            except pywintypes.error as e:
                log(f"  [{label}] write failed: {e.args}")
            t.join(4.0)
            if "data" in got:
                err, data = got["data"]
                log(f"  [{label}] RECV err={err} data={data[:400]!r}")
                if data:
                    log(f"  [{label}] *** GOT REPLY ***")
                    try:
                        h.Close()
                    except Exception:
                        pass
                    return
            elif "err" in got:
                log(f"  [{label}] read err: {got['err']}")
            else:
                log(f"  [{label}] (timeout)")
            try:
                h.Close()
            except Exception:
                pass


def main() -> int:
    pids = sidecar_pids()
    log(f"sidecar pids: {pids}")
    pipe = find_pipe(pids)
    if not pipe:
        log("no agent-code-toolhost pipe found")
        return 1
    try_pipe(pipe)
    io.open("logs/_ipc_attempt.txt", "w", encoding="utf-8").write("\n".join(LOG))
    return 0


if __name__ == "__main__":
    sys.exit(main())
