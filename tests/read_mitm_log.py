"""Read the mitmproxy capture and print the llm_raw_chat / model_list requests.

These are the requests whose body we could not guess - the whole point of the
capture is to see the exact JSON the real sidecar sends.
"""
from __future__ import annotations

import io
import json
import os
import sys

LOG = os.environ.get("MITM_OUT", r"D:\workspace\trae2api\logs\mitm-requests.jsonl")


def main() -> int:
    if not os.path.exists(LOG):
        print(f"no capture at {LOG}")
        return 1
    recs = []
    for line in io.open(LOG, encoding="utf-8"):
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    print(f"{len(recs)} records")

    # what hosts did we see?
    hosts = {}
    for r in recs:
        hosts[r.get("host")] = hosts.get(r.get("host"), 0) + 1
    print("\n=== hosts ===")
    for h, n in sorted(hosts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4}  {h}")

    # paths we care about
    keys = ("llm_raw_chat", "model_list", "get_session_usage", "chat")
    print("\n=== interesting requests ===")
    for r in recs:
        if r.get("kind") != "request":
            continue
        path = r.get("path", "")
        if not any(k in path for k in keys):
            continue
        print(f"\n--- {r['method']} {r['host']}{path} ---")
        print("headers:")
        for k, v in (r.get("headers") or {}).items():
            vv = v if len(v) < 90 else v[:87] + "..."
            print(f"    {k}: {vv}")
        body = r.get("body") or ""
        print(f"body ({len(body)} chars):")
        print(body[:6000])

    print("\n=== their responses (first 3) ===")
    shown = 0
    for r in recs:
        if r.get("kind") != "response":
            continue
        if not any(k in r.get("path", "") for k in keys):
            continue
        print(f"\n--- {r.get('status')} {r['host']}{r['path']} ---")
        print((r.get("body") or "")[:2000])
        shown += 1
        if shown >= 3:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
