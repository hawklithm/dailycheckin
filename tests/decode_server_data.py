"""Minimal, robust decode of iCubeServerData://icube.cloudide.

Kept deliberately simple and self-contained: earlier attempts produced no output
at all, so this version writes results to a file immediately at each step
rather than relying on stdout, making progress observable regardless of console
encoding.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "logs", "_serverdata_min.txt")
STORAGE = os.path.join(os.environ.get("APPDATA", ""), "Trae CN", "User",
                       "globalStorage", "storage.json")
KEY = "iCubeServerData://icube.cloudide"

lines: list[str] = []


def emit(s: str = "") -> None:
    lines.append(s)
    try:
        io.open(LOG, "w", encoding="utf-8").write("\n".join(lines))
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    emit(f"storage: {STORAGE}")
    if not os.path.exists(STORAGE):
        emit("!! storage.json missing")
        return 1
    with io.open(STORAGE, encoding="utf-8") as f:
        data = json.load(f)
    emit(f"keys matching cloudide: "
         f"{[k for k in data if 'cloudide' in k.lower()]}")

    v = data.get(KEY)
    if not isinstance(v, str):
        emit(f"!! {KEY} not a string (got {type(v).__name__})")
        return 1
    emit(f"raw length: {len(v)}")
    emit(f"head: {v[:60]}")
    emit(f"tail: {v[-30:]}")

    raw = None
    for name, fn in (
            ("std+pad", lambda x: base64.b64decode(x + "=" * (-len(x) % 4))),
            ("urlsafe", lambda x: base64.urlsafe_b64decode(
                x.replace("-", "+").replace("_", "/")
                + "=" * (-len(x) % 4))),
    ):
        try:
            out = fn(v)
            emit(f"b64[{name}] -> {len(out)} bytes")
            raw = out
            break
        except Exception as e:  # noqa: BLE001
            emit(f"b64[{name}] failed: {e}")
    if raw is None:
        return 1

    emit(f"head hex: {raw[:24].hex()}")
    emit(f"head ints: {list(raw[:8])}")

    try:
        obj = json.loads(raw.decode("utf-8"))
        emit("PLAINTEXT JSON")
        emit(json.dumps(obj, indent=2, ensure_ascii=False)[:8000])
        return 0
    except Exception as e:  # noqa: BLE001
        emit(f"not plain JSON: {e}")

    for name, fn in (("zlib", zlib.decompress),
                     ("deflate", lambda b: zlib.decompress(b, -15)),
                     ("gzip", lambda b: zlib.decompress(b, 16 + 15))):
        try:
            out = fn(raw)
            emit(f"{name} -> {len(out)} bytes")
            emit(out.decode("utf-8", "replace")[:8000])
            return 0
        except Exception as e:  # noqa: BLE001
            emit(f"{name} failed: {e}")

    # credential scheme
    try:
        from trae2api.credential_decrypt import decrypt_blob
        plain = decrypt_blob(raw)
        if plain:
            emit("decrypted via credential scheme")
            emit(plain.decode("utf-8", "replace")[:8000])
            return 0
        emit("credential scheme: no match")
    except Exception as e:  # noqa: BLE001
        emit(f"credential scheme error: {e}")

    import re
    emit("--- printable runs ---")
    for m in re.finditer(rb"[ -~]{6,150}", raw):
        emit("  " + m.group(0).decode("ascii", "replace"))
    return 0


if __name__ == "__main__":
    try:
        sys.path.insert(0, ROOT)
        rc = main()
    except BaseException as e:  # noqa: BLE001
        import traceback
        emit("EXCEPTION: " + traceback.format_exc())
        rc = 1
    emit(f"--- done rc={rc} ---")
    print("\n".join(lines)[:9000])
    sys.exit(0)
