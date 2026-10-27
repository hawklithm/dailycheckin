"""Decrypt the entitlement blob the client caches locally.

storage.json holds:
  iCubeAuthInfo://icube.cloudide   (2484 b)  -> credentials (already handled)
  iCubeServerData://icube.cloudide (4623 b)  -> "entitlemen..." server data

The second one is new to us. It is the client's cached SERVER DATA, and its
plaintext starts with {"entitlemen... - i.e. the account's entitlement state.
If agent mode is gated server-side, the answer is very likely in here.

This decrypts it with the same scheme as the credentials and dumps the JSON.
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.credential_decrypt import decrypt_value  # noqa: E402

STORAGE = os.path.join(os.environ.get("APPDATA", ""), "Trae CN", "User",
                       "globalStorage", "storage.json")
OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    with io.open(STORAGE, encoding="utf-8") as f:
        data = json.load(f)

    keys = [k for k in data if "cloudide" in k.lower()
            or "serverdata" in k.lower()]
    log(f"candidate keys: {keys}\n")

    for key in keys:
        raw = data.get(key)
        if not isinstance(raw, str):
            continue
        log("=" * 74)
        log(f"### {key}  ({len(raw)} chars)")
        log("=" * 74)
        try:
            plain = decrypt_value(raw)
        except Exception as e:  # noqa: BLE001
            log(f"  decrypt failed: {type(e).__name__}: {e}")
            # fall back to raw inspection
            log(f"  raw head: {raw[:200]}")
            continue
        if isinstance(plain, bytes):
            plain = plain.decode("utf-8", "replace")
        log(f"  plaintext {len(plain)} chars")
        try:
            obj = json.loads(plain)
        except Exception:  # noqa: BLE001
            log("  (not JSON) " + plain[:1500])
            continue

        # walk and surface entitlement / agent / scope related fields
        def walk(o, pre=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    p = f"{pre}.{k}" if pre else k
                    if isinstance(v, (dict, list)):
                        walk(v, p)
                    else:
                        s = str(v)
                        if len(s) > 120:
                            s = s[:120] + "..."
                        log(f"    {p} = {s}")
            elif isinstance(o, list):
                log(f"    {pre} = [list len {len(o)}]")
                for i, v in enumerate(o[:6]):
                    walk(v, f"{pre}[{i}]")

        walk(obj)

        # explicitly hunt agent / solo / v3 switches
        log("\n  --- agent / solo / v3 related values ---")
        blob = plain.lower()
        for needle in ("solo", "agent_process", "v3", "enable", "entitle",
                       "agent_type", "permission", "scope", "pay",
                       "billing", "trial", "quota", "credit"):
            c = blob.count(needle)
            if c:
                log(f"    {needle:16} x{c}")

        log("\n  --- full pretty JSON (truncated 6000) ---")
        log(json.dumps(obj, indent=2, ensure_ascii=False)[:6000])

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_serverdata.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:14000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
