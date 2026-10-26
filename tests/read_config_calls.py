"""What startup config does Trae fetch, and what identifies the chat mode?

The capture shows the renderer calling:
  api.trae.com.cn/service/settings/v3/
  api.trae.com.cn/icube/api/v1/native/config/query
And ai_agent.dll has api/ide/v1/commercial/get_mode_info and api/ide/v1/chat_mode.

The 2001 error wants an "app config record", so find what keys/ids identify it.
"""
import io
import json
import re

CAP = r"D:\workspace\trae2api\logs\mitm-requests.jsonl"

# 1. what did the renderer send to those config endpoints?
recs = []
for line in io.open(CAP, encoding="utf-8"):
    try:
        recs.append(json.loads(line))
    except Exception:
        pass

out = []
out.append("=== config-ish requests from the capture ===")
for r in recs:
    if r.get("kind") != "request":
        continue
    p = r.get("path", "")
    if any(k in p for k in ("settings", "config", "mode", "native")):
        out.append(f"\n--- {r['method']} {r['host']}{p[:140]} ---")
        out.append("  body: " + (r.get("body") or "")[:600])

# 2. the responses to those (they contain the config!)
out.append("\n\n=== responses to config endpoints ===")
for r in recs:
    if r.get("kind") != "response":
        continue
    p = r.get("path", "")
    if any(k in p for k in ("settings", "config", "mode", "native")):
        body = (r.get("body") or "")
        out.append(f"\n--- {r.get('status')} {r['host']}{p[:120]} ({len(body)}b) ---")
        out.append(body[:2500])

io.open("logs/_configs.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
