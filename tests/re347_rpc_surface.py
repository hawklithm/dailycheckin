"""Extract every {service, method} RPC the JS layer invokes on the sidecar."""
import io
import re

wb = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
txt = open(wb, "rb").read().decode("latin-1")
out = []

# service: "x", method: "y"
pairs = {}
for m in re.finditer(r'service:\s*["\'`]([a-z_]+)["\'`]\s*,\s*method:\s*["\'`]([a-z_]+)["\'`]', txt):
    pairs.setdefault(m.group(1), set()).add(m.group(2))

# reversed order
for m in re.finditer(r'method:\s*["\'`]([a-z_]+)["\'`]\s*,\s*service:\s*["\'`]([a-z_]+)["\'`]', txt):
    pairs.setdefault(m.group(2), set()).add(m.group(1))

out.append(f"=== {len(pairs)} services ===")
for svc in sorted(pairs):
    out.append(f"\n[{svc}] ({len(pairs[svc])} methods)")
    for meth in sorted(pairs[svc]):
        out.append(f"    {meth}")

out.append("")
out.append("=== chat-service calls with their data payload (first 6) ===")
n = 0
for m in re.finditer(r'service:\s*["\'`]chat["\'`].{0,400}', txt):
    out.append(re.sub(r"\s+", " ", m.group(0)))
    out.append("-" * 90)
    n += 1
    if n >= 6:
        break

io.open("logs/_rpcsurface.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
