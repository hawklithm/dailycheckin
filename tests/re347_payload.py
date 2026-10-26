"""Extract convertReqToRustPayload - the exact request envelope the renderer sends."""
import io
import re

wb = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
txt = open(wb, "rb").read().decode("latin-1")
out = []


def show(pattern, before=200, after=1500, limit=2, label=""):
    out.append(f"=== {label or pattern} ===")
    n = 0
    for m in re.finditer(pattern, txt):
        seg = txt[max(0, m.start() - before): m.start() + after]
        out.append(re.sub(r"\s+", " ", seg))
        out.append("=" * 100)
        n += 1
        if n >= limit:
            break
    out.append("")


show(r"convertReqToRustPayload\(", 300, 2000, 1, "convertReqToRustPayload body")
show(r"createRequestPacket\(", 200, 1200, 1, "createRequestPacket body")
show(r"createUserInfo\(", 200, 1200, 1, "createUserInfo body")

io.open("logs/_payload347.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
