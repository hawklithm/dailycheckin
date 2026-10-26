"""Locate the app-config key.

Two leads:
1. ai_agent.dll has 3 'AppConfig' hits - dump their contexts to get the struct
   field names, which is what the server looks the record up by.
2. /api/v1/commercial/get_mode_info returned 4001 with
   {"config_info_list":[], "entitlement_id":"", "metadata":{}, "status":0}
   so it TAKES parameters that identify the config. Enumerate them.
"""
from __future__ import annotations

import io
import re

DLL = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
       r"\resources\app\modules\ai-agent\ai_agent.dll")

txt = open(DLL, "rb").read().decode("latin-1")
out = []

out.append("=== AppConfig contexts in ai_agent.dll ===")
for m in re.finditer("AppConfig", txt):
    s = m.start()
    out.append("---")
    out.append(re.sub(r"~{3,}", " | ",
                      re.sub(r"[^\x20-\x7e]", "~", txt[max(0, s - 380):s + 380])))

# neighbouring identifiers (the struct fields are concatenated string literals)
out.append("")
out.append("=== identifiers within 600 bytes before each hit ===")
for m in list(re.finditer("AppConfig", txt))[:3]:
    s = m.start()
    seg = txt[max(0, s - 600):s + 200]
    toks, seen = [], set()
    for t in re.findall(r"[a-z][a-z0-9_]{3,30}", seg):
        if t not in seen:
            seen.add(t)
            toks.append(t)
    out.append("  " + ", ".join(toks))

io.open("logs/_appcfg_src.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
