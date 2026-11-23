"""Which process emits the 28-event stream, and over what transport?

The reachability test showed api/ide/v1/chat only emits
{progress_notice, token_usage, done} (+ prompt/metadata/output), while the
28-event enum lives in harness.dll. harness.dll is the ai-server process
(--vscode-crash-reporter-process-type=ai-server), NOT the sidecar.

If ai-server speaks a DIFFERENT transport to a DIFFERENT endpoint, then
"use the same call logic" means implementing THAT transport, not v1/chat.

Evidence to gather from harness.dll:
  * its own endpoint paths (does it use api/ide/v1/chat at all?)
  * transport hints: websocket / grpc / quic / socket paths
  * the frame/envelope struct names it uses
  * whether it defines its own request envelope distinct from Request
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
HARNESS = os.path.join(TRAE, r"resources\app\modules\ai-agent\harness.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def clean(b: bytes, n: int = 900) -> str:
    return re.sub(rb"[^\x20-\x7e]+", b" | ", b).decode("ascii", "replace")[:n]


def main() -> int:
    with io.open(HARNESS, "rb") as f:
        hb = f.read()

    log("=" * 74)
    log("A. TRANSPORT HINTS in harness.dll")
    log("=" * 74)
    hints = ["ws://", "wss://", "grpc", "quic", "socket", "pipe",
             "\\\\.\\pipe", "WebSocket", "text/event-stream", "http://",
             "https://", "mcp", "stdio", "unix", "named_pipe"]
    for h in hints:
        log(f"  {h:20} x{hb.count(h.encode())}")

    log("\n" + "=" * 74)
    log("B. ENDPOINT PATHS in harness.dll")
    log("=" * 74)
    pat = re.compile(rb"api/[a-z0-9_/]{4,60}")
    paths = sorted({m.group(0).decode("ascii", "replace")
                    for m in pat.finditer(hb)})
    for p in paths:
        log(f"    {p}")

    log("\n" + "=" * 74)
    log("C. harness module layout (source paths)")
    log("=" * 74)
    sp = re.compile(rb"harness\\server\\src\\[a-z0-9_\\/]+\.rs")
    for p in sorted({m.group(0).decode("ascii", "replace")
                     for m in sp.finditer(hb)}):
        log(f"    {p}")

    log("\n" + "=" * 74)
    log("D. envelope-ish struct declarations unique to harness")
    log("=" * 74)
    decl = re.compile(rb"struct ([A-Za-z0-9_]{3,60}) with (\d+) element")
    want = ("Event", "Frame", "Message", "Packet", "Envelope", "Request",
            "Response", "Stream", "Notification", "Command")
    seen = set()
    for m in decl.finditer(hb):
        name = m.group(1).decode("ascii", "replace")
        n = m.group(2).decode("ascii", "replace")
        if any(w in name for w in want) and (name, n) not in seen:
            seen.add((name, n))
    for name, n in sorted(seen):
        log(f"    {name:46} {n:>3} elements")
    log(f"\n  total: {len(seen)}")

    log("\n" + "=" * 74)
    log("E. around the 28-event enum: what wraps it?")
    log("=" * 74)
    p = hb.find(b"task_createdthought")
    if p > 0:
        log(clean(hb[max(0, p - 1500):p + 600], 2100))

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_harness_transport.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:16000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
