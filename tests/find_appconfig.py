"""Find how the sidecar gets its "app config" (the 2001 error's missing piece).

The error is now "failed to get app config: record not found", so the request
passed validation and reached real business logic. Something identifies the app
config - likely a field in the request or a config fetched at startup.

Search ai_agent.dll / harness.dll for the string and its neighbours, plus the
JS layer for the settings endpoints seen in the capture:
  api.trae.com.cn/service/settings/v3/
  api.trae.com.cn/icube/api/v1/native/config/query
"""
import io
import re

FILES = [
    (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
     r"\resources\app\modules\ai-agent\ai_agent.dll", "ai_agent.dll"),
    (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
     r"\resources\app\modules\ai-agent\harness.dll", "harness.dll"),
    (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
     r"\resources\app\out\main.js", "main.js"),
]
out = []

for path, name in FILES:
    txt = open(path, "rb").read().decode("latin-1")
    out.append(f"### {name}")
    for kw in ["failed to get app config", "get app config", "app_config",
               "appConfig", "get_app_config"]:
        n = len(re.findall(re.escape(kw), txt))
        if n:
            out.append(f"  {kw!r}: {n}")
            for m in list(re.finditer(re.escape(kw), txt))[:2]:
                s = m.start()
                seg = txt[max(0, s - 300):s + 300]
                out.append("    " + re.sub(r"~{3,}", " | ",
                                           re.sub(r"[^\x20-\x7e]", "~", seg)))
    out.append("")

# the settings endpoints the renderer calls
wb = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
try:
    t = open(wb, "rb").read().decode("latin-1")
    out.append("### workbench.js settings endpoints")
    for kw in ["service/settings", "native/config/query", "settings/v3",
               "getAppConfig", "app_config"]:
        n = len(re.findall(re.escape(kw), t))
        if n:
            out.append(f"  {kw!r}: {n}")
            for m in list(re.finditer(re.escape(kw), t))[:2]:
                s = m.start()
                out.append("    " + re.sub(r"\s+", " ",
                                           t[max(0, s - 250):s + 300]))
except Exception as e:  # noqa: BLE001
    out.append(f"workbench.js: {e}")

io.open("logs/_appconfig.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
