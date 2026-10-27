"""Inspect iCubeServerData://icube.cloudide - the cached entitlement blob.

It is not decryptable with the credential scheme and is not plain base64.
Try the variants: base64 with padding fixes, URL-safe base64, and the same
"tc\\x05\\x10" header scheme used by credentials (it may use a different key
length or header).
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.credential_decrypt import decrypt_blob  # noqa: E402

STORAGE = os.path.join(os.environ.get("APPDATA", ""), "Trae CN", "User",
                       "globalStorage", "storage.json")
KEY = "iCubeServerData://icube.cloudide"
OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def try_b64(s: str) -> bytes | None:
    for name, fn in (
            ("std+pad", lambda x: base64.b64decode(x + "=" * (-len(x) % 4))),
            ("urlsafe", lambda x: base64.urlsafe_b64decode(
                x.replace("-", "+").replace("_", "/") + "=" * (-len(x) % 4))),
            ("std raw", lambda x: base64.b64decode(x, validate=False)),
    ):
        try:
            out = fn(s)
            if out:
                return out
        except Exception:  # noqa: BLE001
            continue
    return None


def main() -> int:
    with io.open(STORAGE, encoding="utf-8") as f:
        data = json.load(f)
    v = data.get(KEY)
    if not v:
        log(f"!! {KEY} missing")
        return 1

    log(f"raw value: {len(v)} chars")
    log(f"head: {v[:80]}")
    log(f"tail: {v[-40:]}")

    raw = try_b64(v)
    if raw is None:
        log("!! could not base64-decode")
        return 1
    log(f"\ndecoded {len(raw)} bytes")
    log(f"  head hex  : {raw[:24].hex()}")
    log(f"  head bytes: {list(raw[:8])}")

    # is it JSON already?
    try:
        obj = json.loads(raw.decode("utf-8"))
        log("\n*** it is PLAINTEXT JSON ***")
        log(json.dumps(obj, indent=2, ensure_ascii=False)[:6000])
        io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs", "_serverdata.txt"), "w",
            encoding="utf-8").write("\n".join(OUT))
        print("\n".join(OUT)[:12000])
        return 0
    except Exception:  # noqa: BLE001
        log("  not plaintext JSON")

    # try the credential decrypt scheme
    plain = decrypt_blob(raw)
    if plain is not None:
        log("\n*** decrypted with the credential scheme ***")
        text = plain.decode("utf-8", "replace")
        log(text[:6000])
        io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs", "_serverdata.txt"), "w",
            encoding="utf-8").write("\n".join(OUT))
        print("\n".join(OUT)[:12000])
        return 0
    log("  credential scheme did not match either")

    # maybe zlib / gzip
    import zlib
    for name, fn in (("zlib", zlib.decompress),
                     ("raw deflate", lambda b: zlib.decompress(b, -15)),
                     ("gzip", lambda b: zlib.decompress(b, 16 + 15))):
        try:
            out = fn(raw)
            log(f"\n*** {name} worked: {len(out)} bytes ***")
            log(out.decode("utf-8", "replace")[:6000])
            break
        except Exception:  # noqa: BLE001
            continue

    log("\n--- printable strings in the blob ---")
    import re
    for m in re.finditer(rb"[ -~]{6,120}", raw):
        log("  " + m.group(0).decode("ascii", "replace")[:200])

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_serverdata.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("\n".join(OUT)[:4000])
        sys.exit(1)
