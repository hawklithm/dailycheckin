"""Analyse the Trae 3.4.7 sidecar (ai_agent.dll) for the LLM call path.

Compares against the 3.4.4 findings recorded in notes/. Prints what changed:
endpoints, transports, service names, env vars, model-config fields.
"""
import io
import re
import sys

DLL = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
       r"\resources\app\modules\ai-agent\ai_agent.dll")

data = open(DLL, "rb").read()
txt = data.decode("latin-1")
print(f"dll: {len(data)/1e6:.1f} MB")

out = []


def count(label, pat):
    out.append(f"  {label:<30} {len(re.findall(pat, txt))}")


out.append("=== endpoints / transports ===")
for label, pat in [
    ("/api/ide/v1/chat", r"/api/ide/v1/chat"),
    ("/api/ide/v2", r"/api/ide/v2"),
    ("/api/v1/", r"/api/v1/"),
    ("/api/v1/:service/:method", r"/api/v1/:service/:method"),
    ("/ws", r'"/ws"'),
    ("40005", r"40005"),
    ("chat_service", r"chat_service"),
    ("UnifiedTransport", r"UnifiedTransport"),
    ("HttpTransport", r"HttpTransport"),
    ("toolhost", r"toolhost"),
    ("mchost", r"mchost"),
    ("trae-api-cn", r"trae-api-cn"),
]:
    count(label, pat)

out.append("")
out.append("=== chat entry evidence (context) ===")
for pat in [r".{150}before invoking.{120}", r".{120}start handler.{200}"]:
    for m in list(re.finditer(pat, txt))[:3]:
        out.append(re.sub(r"~{3,}", " | ", re.sub(r"[^\x20-\x7e]", "~", m.group(0))))
        out.append("--")

out.append("")
out.append("=== Rust module layout (what changed) ===")
mods = sorted(set(m.group(0) for m in
                  re.finditer(r"ai-agent\\src\\[a-z_]+\\", txt)))
for m in mods:
    out.append("  " + m)
new_files = sorted(set(m.group(0) for m in
                       re.finditer(r"icube_server_rs\\modules\\[a-z\-_]+\\src\\[a-z_]+\\", txt)))
out.append("")
for m in new_files:
    out.append("  " + m)

out.append("")
out.append("=== provider endpoints (who the sidecar calls) ===")
for m in sorted(set(m.group(0) for m in
                    re.finditer(r"/(models|v1)/[a-z0-9_/\-]{2,40}", txt)))[:40]:
    out.append("  " + m)

out.append("")
out.append("=== env vars ===")
envs = set()
for m in re.finditer(r"\b[A-Z][A-Z0-9_]{5,44}\b", txt):
    v = m.group(0)
    if any(k in v for k in ("ICUBE", "TRAE_", "TOOLHOST", "CKG_", "AHA_", "MARSCODE")):
        envs.add(v)
for e in sorted(envs)[:60]:
    out.append("  " + e)

io.open("logs/_re347.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
