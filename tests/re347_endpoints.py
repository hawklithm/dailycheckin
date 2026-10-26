"""Extract every /api/ide/v1/... endpoint from the 3.4.7 sidecar and JS layers."""
import io
import re

DLL = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
       r"\resources\app\modules\ai-agent\ai_agent.dll")
WB = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
MAIN = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\out\main.js")

out = []

for name, path in [("ai_agent.dll", DLL), ("workbench.js", WB), ("main.js", MAIN)]:
    try:
        txt = open(path, "rb").read().decode("latin-1")
    except Exception as e:
        out.append(f"### {name}: READ FAILED {e}")
        continue
    out.append(f"### {name}  ({len(txt)/1e6:.1f} MB)")
    # endpoints appear as adjacent strings; grab the /api/ide/v1 family
    hits = sorted(set(m.group(0) for m in
                      re.finditer(r"/api/ide/v1/[a-z0-9_/\-]{2,50}", txt)))
    out.append(f"  {len(hits)} distinct /api/ide/v1/ paths")
    for h in hits:
        out.append("    " + h)
    out.append("")

    # other API families
    for fam in ("/api/v1/", "/api/v2/", "/api/v3/"):
        hits2 = sorted(set(m.group(0) for m in
                           re.finditer(re.escape(fam) + r"[a-z0-9_/\-]{2,40}", txt)))
        out.append(f"  {fam} -> {len(hits2)}")
        for h in hits2[:20]:
            out.append("    " + h)
        out.append("")

io.open("logs/_endpoints347.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
