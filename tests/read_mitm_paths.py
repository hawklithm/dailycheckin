"""Find the real LLM/chat request in the capture.

The capture shows Trae talks to api.trae.cn / api.trae.com.cn, NOT
trae-api-cn.mchost.guru. List every distinct path with method and body size so
we can spot the chat call by shape rather than by guessing its name.
"""
from __future__ import annotations

import io
import json
import os
import sys

LOG = os.environ.get("MITM_OUT", r"D:\workspace\trae2api\logs\mitm-requests.jsonl")


def main() -> int:
    recs = []
    for line in io.open(LOG, encoding="utf-8"):
        try:
            recs.append(json.loads(line))
        except Exception:
            pass

    reqs = [r for r in recs if r.get("kind") == "request"]
    print(f"{len(recs)} records, {len(reqs)} requests\n")

    print("=== every request path (method, body size) ===")
    seen = {}
    for r in reqs:
        key = (r["method"], r["host"], r["path"].split("?")[0])
        e = seen.setdefault(key, {"n": 0, "max": 0, "total": 0})
        e["n"] += 1
        b = len(r.get("body") or "")
        e["max"] = max(e["max"], b)
        e["total"] += b
    for (m, h, p), e in sorted(seen.items(), key=lambda kv: -kv[1]["max"]):
        print(f"  {m:6} {h:22} {p[:70]:70} n={e['n']:<3} max={e['max']}")

    print("\n=== requests with a non-empty body, sorted by size ===")
    big = sorted((r for r in reqs if r.get("body")),
                 key=lambda r: -len(r["body"]))
    for r in big[:25]:
        print(f"  {len(r['body']):>7}b  {r['method']:5} {r['host']}{r['path'][:80]}")

    print("\n=== bodies of the largest 6 ===")
    for r in big[:6]:
        print(f"\n----- {r['method']} {r['host']}{r['path'][:120]} "
              f"({len(r['body'])}b) -----")
        print(r["body"][:5000])

    io.open("logs/_mitm_summary.txt", "w", encoding="utf-8").write(
        "\n".join(f"{r['method']} {r['host']}{r['path']}\n{r['body'][:20000]}"
                  for r in big[:20]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
