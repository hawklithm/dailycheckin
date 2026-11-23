"""Locate the definition of convertReqToRustPayload (async name(payload))."""
import io
import re

wb = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
txt = open(wb, "rb").read().decode("latin-1")
out = []

# definition form: async convertReqToRustPayload(e,t,s){ ... }
for m in re.finditer(r"async convertReqToRustPayload\(", txt):
    s = m.start()
    out.append(f"--- def @{s} ---")
    out.append(re.sub(r"\s+", " ", txt[s:s + 2600]))
    out.append("")
    break

# also the non-async form
for m in re.finditer(r"convertReqToRustPayload\(\w+,\w+,\w+\)\{", txt):
    s = m.start()
    out.append(f"--- alt def @{s} ---")
    out.append(re.sub(r"\s+", " ", txt[s:s + 2600]))
    break

io.open("logs/_convertdef.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
