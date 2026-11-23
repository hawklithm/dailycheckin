"""Extract the authoritative RPC-method <-> HTTP-path <-> event mapping table.

Found in harness.dll:

    chat.start_chat/api/v1/chat/start_chatstart_chat
    chat.legacy_chat
    chat.start_resume_chat/api/v1/chat/start_resume_chatstart_resume_chat
    chat.stop_chat/api/v1/chat/stop_chatstop_chat
    chat.subscribe_events/api/v1/chat/subscribe_eventssubscribe_events

Pattern per entry:  <dotted.name>/<api/path><suffix>

This is the mapping the client itself uses, so it tells us exactly:
  * which RPC name the renderer calls
  * which HTTP path that maps to
  * and what follows (an event/route name)

Notably `chat.legacy_chat` has NO api path - consistent with it being the old
endpoint (api/ide/v1/chat) while start_chat/subscribe_events are the newer
agent-mode pair.

This harvests the whole table by scanning for the `<word>.<word>/api/` shape.
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
FILES = [
    (os.path.join(TRAE, r"resources\app\modules\ai-agent\harness.dll"),
     "harness.dll"),
    (os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll"),
     "ai_agent.dll"),
]

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


# <ns>.<method>/api/<rest>
PAT = re.compile(rb"([a-z][a-z0-9_]{1,20}\.[a-z][a-z0-9_]{1,40})"
                 rb"/(api/[a-z0-9_/]{2,60})")


def main() -> int:
    for path, label in FILES:
        if not os.path.exists(path):
            continue
        with io.open(path, "rb") as f:
            buf = f.read()
        log("=" * 76)
        log(f"### {label}")
        log("=" * 76)

        rows = []
        for m in PAT.finditer(buf):
            rpc = m.group(1).decode("ascii", "replace")
            api = m.group(2).decode("ascii", "replace")
            rows.append((rpc, api))

        # dedupe preserving order
        seen = set()
        uniq = []
        for rpc, api in rows:
            k = (rpc, api)
            if k in seen:
                continue
            seen.add(k)
            uniq.append((rpc, api))

        log(f"\n  mapping entries: {len(uniq)}\n")
        log(f"  {'RPC method':40} -> HTTP path")
        log("  " + "-" * 74)
        for rpc, api in uniq:
            log(f"  {rpc:40} -> {api}")

        # namespaces seen
        ns = {}
        for rpc, _ in uniq:
            n = rpc.split(".")[0]
            ns[n] = ns.get(n, 0) + 1
        log(f"\n  namespaces: {ns}")

        # entries with no api path (the "legacy" ones)
        log("\n  --- dotted names WITHOUT an api path (legacy / local-only) ---")
        bare = re.compile(rb"([a-z][a-z0-9_]{1,20}\.[a-z][a-z0-9_]{1,40})")
        # only report ones whose next byte is not '/'
        names = set()
        for m in bare.finditer(buf):
            if m.end() < len(buf) and buf[m.end():m.end() + 1] == b"/":
                continue
            names.add(m.group(1).decode("ascii", "replace"))
        for n in sorted(names):
            if "." in n:
                log(f"    {n}")
        log("")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_rpc_http_map.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
