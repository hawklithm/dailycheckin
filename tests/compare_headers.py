"""Compare the headers our proxy sends with what real Trae sends.

The capture has real Trae requests to api.trae.cn / api.trae.com.cn. If the
gateway validates version/app headers, our stale trae-cn/3.4.4 User-Agent and
hardcoded x-ide-version-code could be exactly why the 3.4.7-only endpoints
(api/ide/v2/llm_raw_chat, api/ide/v1/model_list) answer 4001.
"""
from __future__ import annotations

import io
import json
import os
import sys

LOG = r"D:\workspace\trae2api\logs\mitm-requests.jsonl"
OUT = r"D:\workspace\trae2api\logs\_hdr_compare.txt"

# what our gateway sends (trae2api/gateway.py DEV_* + _headers())
OURS = {
    "User-Agent": "trae-cn/3.4.4",
    "X-App-Id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
    "x-plugin-channel": "icube-ai",
    "x-ide-version-code": "20260212",
    "X-Trae-Client-Type": "ide",
    "X-Device-Cpu": "AMD",
    "X-Device-Brand": "MS-7B89",
    "X-Device-Type": "windows",
    "X-Os-Version": "10",
    "Authorization": "Cloud-IDE-JWT <jwt>",
    "x-ide-token": "<jwt>",
    "X-User-Region": "CN",
}


def main() -> int:
    recs = []
    for line in io.open(LOG, encoding="utf-8"):
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    reqs = [r for r in recs if r.get("kind") == "request"]

    # pick a POST with a body - those are the API calls, not OPTIONS preflight
    api = [r for r in reqs if r.get("body")]
    sample = api[0] if api else reqs[0]

    out = []
    out.append(f"=== real Trae request used as reference ===")
    out.append(f"{sample['method']} {sample['host']}{sample['path'][:100]}")
    out.append("")
    out.append("=== headers real Trae sends ===")
    real = sample.get("headers") or {}
    for k in sorted(real, key=str.lower):
        v = real[k]
        vv = v if len(v) < 110 else v[:107] + "..."
        out.append(f"  {k}: {vv}")

    out.append("")
    out.append("=== what our proxy sends ===")
    for k, v in OURS.items():
        out.append(f"  {k}: {v}")

    out.append("")
    out.append("=== headers real Trae has that we do NOT ===")
    real_l = {k.lower() for k in real}
    our_l = {k.lower() for k in OURS}
    for k in sorted(real_l - our_l):
        # find the original-cased key
        orig = next((rk for rk in real if rk.lower() == k), k)
        v = real[orig]
        vv = v if len(v) < 110 else v[:107] + "..."
        out.append(f"  {orig}: {vv}")

    out.append("")
    out.append("=== headers we send that real Trae does NOT ===")
    for k in sorted(our_l - real_l):
        out.append(f"  {k}")

    # look for any version-ish header in the real traffic
    out.append("")
    out.append("=== version-ish headers in real traffic ===")
    for k, v in real.items():
        if any(s in k.lower() for s in ("version", "app", "client", "ide", "trae")):
            vv = v if len(v) < 130 else v[:127] + "..."
            out.append(f"  {k}: {vv}")

    io.open(OUT, "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
