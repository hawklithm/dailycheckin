"""Follow the endpoint the client ACTUALLY uses for chat.

grep_urls turned up cue_agent paths in the plaintext logs:
    /api/cue_agent/v3/create_agent_task           x1
    /api/cue_agent/v3/commit_toolcall_result      x1
while `llm_raw_chat` never appears ANYWHERE in the client's logs (grep across
all plaintext logs: 0 hits). That suggests llm_raw_chat is not the public chat
entry the renderer uses - it may be internal-only to the sidecar, with no
server-side provisioning for external callers (hence the permanent 4011).

This digs out every cue_agent / /api/cue* reference with its surrounding log
context so we can see the real chat transport.
"""
from __future__ import annotations

import io
import os
import re
import sys

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
ROOT = os.path.join(APPDATA, "Trae CN")

PAT = re.compile(r"/api/cue[A-Za-z0-9_/-]*")
OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    from collections import Counter
    hits: Counter = Counter()
    ctx: dict[str, list[str]] = {}

    for base, _d, fs in os.walk(ROOT):
        for fn in fs:
            p = os.path.join(base, fn)
            if not fn.lower().endswith((".log", ".txt", ".json")):
                continue
            try:
                if os.path.getsize(p) > 250 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    if b"\x00" in f.read(4096):
                        continue
                with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:  # noqa: BLE001
                continue
            for i, ln in enumerate(lines):
                for m in PAT.finditer(ln):
                    path = m.group(0)
                    hits[path] += 1
                    rel = p.replace(ROOT, "")
                    ctx.setdefault(path, [])
                    if len(ctx[path]) < 3:
                        ctx[path].append(
                            f"[{rel}:{i+1}] " + ln.rstrip("\n")[:700])

    log("=== cue_agent paths found in plaintext logs ===")
    if not hits:
        log("  (none)")
    for path, n in hits.most_common(30):
        log(f"\n--- {path}   x{n}")
        for c in ctx.get(path, []):
            log("    " + c)

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_cuepaths.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
