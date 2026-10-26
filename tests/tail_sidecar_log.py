"""Tail the live sidecar alaudalog and report growth while Trae is used."""
import glob
import io
import os
import sys
import time

SECS = float(os.environ.get("WATCH_SECONDS", "45"))

cands = sorted(glob.glob(
    r"C:\Users\marcus\AppData\Roaming\Trae CN\logs\*\Modular\ai_agent-0-*.alaudalog"),
    key=os.path.getmtime, reverse=True)
PATH = cands[0]
print(f"watching {PATH} for {SECS:.0f}s")

fh = open(PATH, "rb")
fh.seek(0, os.SEEK_END)
size0 = fh.tell()
print(f"initial size {size0}")

t0 = time.time()
buf = b""
last = 0
while time.time() - t0 < SECS:
    fh.seek(0, os.SEEK_END)
    size = fh.tell()
    if size > size0:
        fh.seek(size0)
        buf += fh.read(size - size0)
        size0 = size
        print(f"  +{size - last} bytes (total new {len(buf)})")
        last = size
    time.sleep(0.5)

fh.close()
print(f"\ngot {len(buf)} new bytes")
if not buf:
    print("no growth - the log is likely buffered; try again while the chat is streaming")
    sys.exit(0)

out = []
out.append(f"new bytes: {len(buf)}")
out.append("--- hex head ---")
out.append(buf[:300].hex())
for enc in ("utf-16-le", "utf-8"):
    try:
        txt = buf.decode(enc, errors="replace")
    except Exception:
        continue
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in txt[:3000])
    out.append(f"--- {enc} (cjk={has_cjk}) ---")
    out.append(txt[:2500])
out.append("--- latin1 ---")
out.append(buf[:1200].decode("latin-1", "replace"))
io.open("logs/_sidecar_tail.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
