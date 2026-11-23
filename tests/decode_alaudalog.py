"""Decode Trae's .alaudalog (magic 'AalG') files.

Header seen: 41 61 6c 47 ('AalG') 00 00 00 00 41 74 61 62 ('Atab') 00 00 00 00
Then a u64 (0x98 = 152) that looks like a table size.

Guess: 'AalG' = header, 'Atab' = a string table, then length-prefixed records.
We dump structure and any UTF-8/UTF-16 runs instead of assuming a codec.
"""
import io
import re
import struct
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else None
if not PATH:
    import glob
    import os
    cands = sorted(glob.glob(r"C:\Users\marcus\AppData\Roaming\Trae CN\logs\*\Modular\ai_agent-0-*.alaudalog"),
                   key=os.path.getmtime, reverse=True)
    PATH = cands[0] if cands else None
    print("auto-selected:", PATH)

data = open(PATH, "rb").read()
print(f"file: {PATH} ({len(data)/1e3:.1f} KB)")

out = []
out.append(f"magic: {data[:4]!r}")
# find all fourcc tags in the first 64 bytes
tags = [(i, data[i:i+4]) for i in range(0, min(64, len(data) - 4))]
out.append("first-64 tags: " + ", ".join(f"{i}:{t.decode('latin-1')}" for i, t in tags if all(32 <= b < 127 for b in t)))

# scan the whole file for ASCII tags that look like 4cc
alltags = {}
for i in range(len(data) - 3):
    t = data[i:i+4]
    if all(65 <= b <= 122 for b in t) and (b"A" <= t[0:1] <= b"z"):
        s = t.decode("latin-1")
        if s.isalpha() and (s[0].isupper() or s.islower()):
            alltags[s] = alltags.get(s, 0) + 1
out.append("\ntop 4cc-looking tags:")
for s, n in sorted(alltags.items(), key=lambda kv: -kv[1])[:25]:
    out.append(f"  {s} x{n}")

# try zlib/deflate on chunks after the header
out.append("\n=== compression probe ===")
import zlib
for off in (16, 24, 32, 152):
    if off >= len(data):
        continue
    for wbits in (15, -15, 31, 47):
        try:
            d = zlib.decompressobj(wbits)
            dec = d.decompress(data[off:off + 4096])
            if len(dec) > 50:
                out.append(f"  off={off} wbits={wbits} -> {len(dec)} bytes: {dec[:120]!r}")
                break
        except Exception:
            pass

# UTF-16LE and UTF-8 runs
for enc, label in (("utf-16-le", "utf16"), ("utf-8", "utf8")):
    try:
        if enc == "utf-8":
            txt = data.decode("utf-8", errors="ignore")
        else:
            txt = data.decode("utf-16-le", errors="ignore")
    except Exception:
        continue
    runs = [m.group(0) for m in re.finditer(r"[\u4e00-\u9fff\w \-:\[\]/\.]{12,}", txt)]
    out.append(f"\n=== {label} runs: {len(runs)} (first 25) ===")
    for r in runs[:25]:
        out.append("  " + r[:160])

io.open("logs/_alaud.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
