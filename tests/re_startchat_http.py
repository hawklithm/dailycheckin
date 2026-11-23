"""方案A: what HTTP does ChatHandler::start_chat actually call?

We know from logs the real renderer issues:
    chat.start_chat          (117 hits)
    lite.subscribe_events    (173 hits)
    lite.create_chat_session
over mojo RPC. We also know api/ide/v1/chat is never mentioned by the client.

So: inside ai_agent.dll, find what start_chat does on the wire. Look for
  * URLs referenced near the ChatHandler / chat service code
  * the SSE/stream client setup (which host/path it posts to)
  * any "request to server" helper names in the chat module
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
DLL = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def clean(b: bytes, n: int = 1400) -> str:
    return re.sub(rb"[^\x20-\x7e]+", b" | ", b).decode("ascii", "replace")[:n]


def main() -> int:
    with io.open(DLL, "rb") as f:
        buf = f.read()

    # 1. Where is start_chat handled?
    log("=" * 74)
    log("A. start_chat occurrences and their neighbourhood")
    log("=" * 74)
    seen = 0
    for m in re.finditer(rb"start_chat", buf):
        p = m.start()
        frag = buf[max(0, p - 500):p + 700]
        txt = clean(frag, 1200)
        if len(txt.strip(" |")) < 40:
            continue
        log(f"\n--- @{p} ---")
        log("  " + txt)
        seen += 1
        if seen >= 8:
            break

    # 2. chat service module: which URLs live near it?
    log("\n" + "=" * 74)
    log("B. URLs near src/domain/chat or src/service/chat")
    log("=" * 74)
    for anchor in (rb"src\\domain\\chat", rb"src\\service\\chat",
                   rb"src\\domain\\model\\service",
                   rb"src\\infrastructure\\adapter"):
        for m in re.finditer(anchor, buf):
            p = m.start()
            # scan a wide window for api/ paths
            win = buf[max(0, p - 3000):p + 3000]
            paths = set(re.findall(rb"api/[a-z0-9_/]{4,50}", win))
            if paths:
                log(f"\n  anchor @{p} {m.group(0).decode('ascii','replace')}")
                for q in sorted(paths):
                    log(f"      {q.decode('ascii', 'replace')}")
            break

    # 3. the stream client: what does it POST to?
    log("\n" + "=" * 74)
    log("C. streaming client hints in chat module")
    log("=" * 74)
    for needle in (b"text/event-stream", b"event-stream",
                   b"chat/completions", b"llm_raw_chat",
                   b"api/ide/v1/chat", b"stream_request"):
        c = buf.count(needle)
        log(f"\n  {needle.decode():22} x{c}")
        if 0 < c < 40:
            p = buf.find(needle)
            log("    " + clean(buf[max(0, p - 400):p + 400], 800))

    # 4. subscribe_events implementation hints
    log("\n" + "=" * 74)
    log("D. subscribe_events neighbourhood")
    log("=" * 74)
    n = 0
    for m in re.finditer(rb"subscribe_events", buf):
        p = m.start()
        txt = clean(buf[max(0, p - 400):p + 500], 900)
        if len(txt.strip(" |")) < 30:
            continue
        log(f"\n--- @{p} ---")
        log("  " + txt)
        n += 1
        if n >= 5:
            break

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_startchat_http.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:16000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
