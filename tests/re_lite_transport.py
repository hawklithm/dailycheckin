"""Critical: what URL does the lite send_message/start_chat POST to?

Two strong leads just appeared in ai_agent.dll:

1. [lite][send_message] request method=start_chat
   [lite][send_message] request: <payload>
   [lite][send_message] response: code=..., message=..., data=...
   -> lite is the module that actually drives chat, and it logs its payload.
      Its source is src/domain/lite/service.rs, and it has subscribe_events.

2. A table of provider endpoint fragments:
      /models/chat/completions   deepseek  /v1/models  /v1/messages
      anthropic  openrouter  openai  /foundation-models/openai/v1/chat/completions
      aws  xai   https://bedrock[-runtime].<region>.amazonaws.com/...
   -> this is the CUSTOM MODEL / BYO-key adapter (provider=...), i.e. the
      "paygo" pool. Useful to know but not the first-party path.

3. VsockAiAgentClient: POST http://localhost ... Host: localhost,
   Accept: text/event-stream  -> for VM/remote runtimes.

The question that decides the design: for a normal desktop chat, does lite
talk to a REMOTE https host (and which path), or only over mocha/vsock?

This script digs out the lite service's HTTP client target and its request
builder field names.
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


def clean(b: bytes, n: int = 1600) -> str:
    return re.sub(rb"[^\x20-\x7e]+", b" | ", b).decode("ascii", "replace")[:n]


def main() -> int:
    with io.open(DLL, "rb") as f:
        buf = f.read()

    log("=" * 74)
    log("A. lite service: request/response logging + transport")
    log("=" * 74)
    for needle in (b"[lite][send_message] request method",
                   b"[lite][send_message] request:",
                   b"[lite][send_message] response:",
                   b"[lite][send_message] result:",
                   b"ai_agent_client.rs",
                   b"VsockAiAgentClient",
                   b"http://localhost"):
        p = buf.find(needle)
        log(f"\n  --- {needle.decode('ascii', 'replace')} @{p} ---")
        if p < 0:
            log("    (absent)")
            continue
        log("    " + clean(buf[max(0, p - 600):p + 900], 1500))

    log("\n" + "=" * 74)
    log("B. lite transport endpoints (paths near lite/service.rs)")
    log("=" * 74)
    for m in re.finditer(rb"src\\domain\\lite\\service\.rs", buf):
        p = m.start()
        win = buf[max(0, p - 6000):p + 6000]
        for pat, label in ((rb"https?://[a-zA-Z0-9./:_-]{6,60}", "url"),
                           (rb"api/[a-z0-9_/]{4,50}", "api path"),
                           (rb"/[a-z0-9_/]{8,50}", "path-ish")):
            found = sorted({x.group(0).decode("ascii", "replace")
                            for x in re.finditer(pat, win)})
            if found:
                log(f"\n  [{label}] near @{p}:")
                for q in found[:25]:
                    log(f"      {q}")
        break

    log("\n" + "=" * 74)
    log("C. the request struct lite builds (field names)")
    log("=" * 74)
    # look for the send_message / StartChatArgs struct declaration
    for name in (b"StartChatArgs", b"SendMessageArgs", b"ChatStartArgs",
                 b"LiteRequest", b"LiteResponse", b"SendMsgArgs"):
        p = buf.find(name)
        if p < 0:
            continue
        log(f"\n  --- {name.decode()} @{p} ---")
        log("    " + clean(buf[max(0, p - 900):p + 400], 1300))

    log("\n" + "=" * 74)
    log("D. custom-model / BYO provider endpoint table (for reference)")
    log("=" * 74)
    p = buf.find(b"/models/chat/completions")
    if p > 0:
        log("  " + clean(buf[max(0, p - 500):p + 1200], 1700))

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_lite_transport.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:16000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
