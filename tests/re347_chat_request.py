"""Extract the chat request construction in the 3.4.7 workbench.

Targets: createRequestPacket / executeRequest / the chat service call that
carries model, prompt, tools. We look for the LLM-facing field names.
"""
import io
import re

wb = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")
txt = open(wb, "rb").read().decode("latin-1")
out = []


def show(pattern, before=200, after=400, limit=4, label=""):
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


show(r"createRequestPacket", 250, 300, 2, "createRequestPacket definition")
show(r"sendRequest\(\"request\"", 250, 350, 2, "sendRequest('request')")
show(r'"chat"\s*,\s*method', 150, 350, 3, "chat service call")

# the model / prompt fields that reach the sidecar
out.append("=== LLM-facing field names present in workbench ===")
for f in ["model_name", "modelName", "prompt_set", "promptSet", "reasoning_effort",
          "reasoningEffort", "chat_type", "chatType", "agent_type", "agentType",
          "config_name", "configName", "ab_version", "abVersion", "context_window",
          "max_tokens", "maxTokens", "tool_choice", "toolChoice", "scene_location",
          "sceneLocation", "custom_model", "customModel"]:
    n = len(re.findall(re.escape(f), txt))
    if n:
        out.append(f"  {f:<18} {n}")

out.append("")
out.append("=== one context per present field ===")
for f in ["model_name", "prompt_set", "reasoning_effort", "chat_type",
          "config_name", "ab_version", "context_window", "max_tokens", "scene_location"]:
    n = len(re.findall(re.escape(f), txt))
    if not n:
        continue
    m = re.search(re.escape(f), txt)
    out.append(f"--- {f} ({n}) ---")
    out.append(re.sub(r"\s+", " ", txt[max(0, m.start() - 250):m.start() + 300]))

io.open("logs/_chatreq347.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
