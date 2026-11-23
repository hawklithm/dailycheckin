"""Check whether the sidecar database is SQLCipher-encrypted and how it is keyed.

database.db has a random 16-byte header instead of "SQLite format 3", so it is
not plain SQLite. This script greps the sidecar binaries for wallet/sqlcipher
strings and looks for a passphrase source we could reuse.
"""
from __future__ import annotations

import io
import os
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"

NEEDLES = [
    b"sqlcipher", b"SQLCIPHER", b"SQLite format 3", b"PRAGMA key",
    b"pragma key", b"cipher_page_size", b"cipher_default_kdf_iter",
    b"cipher_hmac_algorithm", b"kdf_iter", b"raw_key",
    b"rekey", b"sqlite3_key", b"SET FOREIGN_KEYS",
    b"wrong final block length", b"file is not a database",
]

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def scan(path: str) -> None:
    size = os.path.getsize(path)
    log(f"### {path}  ({size/1048576:.1f} MB)")
    hits: dict[bytes, int] = {}
    with io.open(path, "rb") as f:
        step = 8 * 1024 * 1024
        prev = b""
        while True:
            chunk = f.read(step)
            if not chunk:
                break
            buf = prev + chunk
            for n in NEEDLES:
                c = buf.count(n)
                if c:
                    hits[n] = hits.get(n, 0) + c
            prev = buf[-64:]
    if hits:
        for n, c in sorted(hits.items(), key=lambda kv: -kv[1]):
            log(f"    {n!r:32} x{c}")
    else:
        log("    (no sqlcipher markers)")
    log("")


def main() -> int:
    targets = []
    for root, _dirs, files in os.walk(TRAE):
        for fn in files:
            if fn.lower() in ("ai_agent.dll", "harness.dll", "toolhost.dll",
                              "ai-agent.exe"):
                targets.append(os.path.join(root, fn))
    if not targets:
        log(f"!! no sidecar binaries under {TRAE}")
    for t in targets:
        try:
            scan(t)
        except Exception as e:  # noqa: BLE001
            log(f"### {t}: ERROR {e}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_dbcipher.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
