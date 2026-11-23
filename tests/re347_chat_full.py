"""Extract the full chat request object the renderer sends to the sidecar.

We know: service "chat", method "chat", and data carries model_name /
custom_model.config_name / model_auto_selection. Find the builder that
assembles the whole request.
"""
import io
import re

wb = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
txt = open(wb, "rb").read().decode("latin-1")
out = []


def show(pattern, before=350, after=700, limit=3, label=""):
    out.append(f"=== {label or pattern} ===")
    n = 0
    for m in re.finditer(pattern, txt):
        seg = txt[max(0, m.start() - before): m.start() + after]
        out.append(re.sub(r"\s+", " ", seg))
        out.append("-" * 90)
        n += 1
        if n >= limit:
            break
    out.append("")


# the request wrapper: {request: {service, method, data}, context, ...}
show(r'request:\{service:"chat"', 300, 700, 2, 'request:{service:"chat"}')
show(r'service:"chat",method:"chat"', 200, 800, 2, 'service:"chat",method:"chat"')

# find all sites that build a chat request
out.append("=== all service:'chat' occurrences ===")
for i, m in enumerate(re.finditer(r'service:\s*"chat"', txt)):
    s = m.start()
    seg = re.sub(r"\s+", " ", txt[max(0, s - 400):s + 900])
    out.append(f"--- #{i} @{s} ---")
    out.append(seg)
    if i >= 5:
        break

io.open("logs/_chatreqfull.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
