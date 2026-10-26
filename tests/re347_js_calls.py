"""How does the JS layer call llm_raw_chat / model_list? Extract request shapes."""
import io
import re

FILES = {
    "workbench.js": (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
                     r"\resources\app\out\vs\workbench\workbench.desktop.main.js"),
    "main.js": (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
                r"\resources\app\out\main.js"),
}
out = []
for name, path in FILES.items():
    txt = open(path, "rb").read().decode("latin-1")
    out.append(f"### {name}")
    for kw in ["llm_raw_chat", "llmRawChat", "raw_chat", "model_list", "modelList",
               "getModelList", "session_usage", "sessionUsage"]:
        n = len(re.findall(re.escape(kw), txt))
        if n:
            out.append(f"  {kw:<16} {n}")
    out.append("")

# context in workbench for the raw chat call
wb = open(FILES["workbench.js"], "rb").read().decode("latin-1")
out.append("=== llm_raw_chat context in workbench ===")
for m in list(re.finditer(r".{250}llm_raw_chat.{350}", wb))[:4]:
    out.append(re.sub(r"\s+", " ", m.group(0)))
    out.append("-" * 100)

out.append("")
out.append("=== chat request builder (service/method names used by TransportManager) ===")
for m in list(re.finditer(r'.{100}service:\s*["\'`]chat[^"\'`]*["\'`].{250}', wb))[:4]:
    out.append(re.sub(r"\s+", " ", m.group(0)))
    out.append("-" * 100)

io.open("logs/_jscall347.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
