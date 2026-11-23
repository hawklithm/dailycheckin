"""Find chat request sites by locating 'chat' service references robustly."""
import io
import re

wb = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
txt = open(wb, "rb").read().decode("latin-1")
out = []

# any place that mentions chat as a service string
pats = [
    r'["\'`]chat["\'`]\s*[,}]',
    r'service\s*[:=]\s*["\'`]chat["\'`]',
    r'method\s*[:=]\s*["\'`]chat["\'`]',
]
for p in pats:
    hits = list(re.finditer(p, txt))
    out.append(f"=== {p}  -> {len(hits)} hits ===")
    for i, m in enumerate(hits[:4]):
        seg = re.sub(r"\s+", " ", txt[max(0, m.start() - 500):m.start() + 900])
        out.append(f"--- #{i} ---")
        out.append(seg)
        out.append("")
    out.append("")

# Also: the stream request builder (executeStreamRequest)
out.append("=== executeStreamRequest callers (the real chat streaming) ===")
for i, m in enumerate(re.finditer(r"executeStreamRequest", txt)):
    s = m.start()
    seg = re.sub(r"\s+", " ", txt[max(0, s - 700):s + 500])
    out.append(f"--- #{i} ---")
    out.append(seg)
    out.append("")
    if i >= 3:
        break

io.open("logs/_chatsites.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
