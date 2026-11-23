"""Extract api/ide/v1/* paths (no leading slash - Rust packs string literals)."""
import io
import re

FILES = {
    "ai_agent.dll": (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
                     r"\resources\app\modules\ai-agent\ai_agent.dll"),
    "toolhost.dll": (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
                     r"\resources\app\modules\ai-agent\toolhost.dll"),
    "harness.dll": (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
                    r"\resources\app\modules\ai-agent\harness.dll"),
    "workbench.js": (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
                     r"\resources\app\out\vs\workbench\workbench.desktop.main.js"),
    "main.js": (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
                r"\resources\app\out\main.js"),
}

out = []
for name, path in FILES.items():
    try:
        txt = open(path, "rb").read().decode("latin-1")
    except Exception as e:
        out.append(f"### {name}: FAILED {e}\n")
        continue
    hits = sorted(set(m.group(0) for m in
                      re.finditer(r"api/ide/v1/[a-z0-9_/\-]{2,60}", txt)))
    out.append(f"### {name} ({len(txt)/1e6:.1f} MB) - {len(hits)} paths")
    for h in hits:
        out.append("    " + h)
    out.append("")

io.open("logs/_ide_endpoints.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
