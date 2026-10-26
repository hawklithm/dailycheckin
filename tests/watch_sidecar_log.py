"""Read the sidecar's live log (alaudalog) while we use Trae, to capture the
real llm_raw_chat request.

The .alaudalog is locked while Trae runs; we read via FileShare ReadWrite.
"""
import io
import os
import sys
import time

PATH = sys.argv[1] if len(sys.argv) > 1 else None
SECS = float(os.environ.get("WATCH_SECONDS", "20"))

import glob

if not PATH:
    cands = sorted(glob.glob(
        r"C:\Users\marcus\AppData\Roaming\Trae CN\logs\*\Modular\ai_agent-0-*.alaudalog"),
        key=os.path.getmtime, reverse=True)
    PATH = cands[0] if cands else None
if not PATH:
    print("no log file")
    sys.exit(1)

print(f"watching {PATH} for {SECS}s")
size0 = os.path.getsize(PATH)
t0 = time.time()
chunks = []
while time.time() - t0 < SECS:
    try:
        fh = open(PATH, "rb")
        fh.seek(0, 2)
        size = fh.tell()
        if size > size0:
            fh.seek(size0)
            chunks.append(fh.read(size - size0))
            size0 = size
        fh.close()
    except Exception as e:  # noqa: BLE001
        print("read err", e)
    time.sleep(1.0)

data = b"".join(chunks)
print(f"got {len(data)} new bytes")
# try utf-16le and utf-8
for enc in ("utf-16-le", "utf-8"):
    try:
        txt = data.decode(enc, errors="replace")
    except Exception:
        continue
    if any("\u4e00" <= c <= "\u9fff" for c in txt[:2000]) or "llm" in txt.lower():
        print(f"--- decoded as {enc} ---")
        print(txt[:3000])
        break
else:
    print("--- hex head ---")
    print(data[:400].hex())
    print("--- latin1 head ---")
    print(data[:800].decode("latin-1", "replace"))
