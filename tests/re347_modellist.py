"""modelList in workbench.js: how the JS obtains the model list and chat params."""
import io
import re

wb = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
txt = open(wb, "rb").read().decode("latin-1")
out = []

out.append("=== modelList contexts ===")
for m in list(re.finditer(r".{200}modelList.{300}", txt))[:8]:
    out.append(re.sub(r"\s+", " ", m.group(0)))
    out.append("-" * 100)

out.append("")
out.append("=== chat/model_list related service+method (RPC names) ===")
for m in list(re.finditer(r'service:\s*["\'`](chat|lite|model)[^"\'`]{0,20}["\'`]', txt))[:20]:
    s = m.start()
    out.append(re.sub(r"\s+", " ", txt[max(0, s-120):s+220]))
    out.append("--")

io.open("logs/_modellist.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
