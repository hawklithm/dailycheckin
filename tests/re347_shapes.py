"""Find the exact request body for llm_raw_chat and model_list.

The sidecar builds these; we extract the field names that appear next to the
endpoint strings and in the LLMAdapter logs.
"""
import io
import re

DLL = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
       r"\resources\app\modules\ai-agent\ai_agent.dll")
txt = open(DLL, "rb").read().decode("latin-1")
out = []


def ctx(pattern, before=300, after=600, limit=3, label=""):
    out.append(f"=== {label or pattern} ===")
    n = 0
    for m in re.finditer(pattern, txt):
        seg = txt[max(0, m.start() - before): m.start() + after]
        out.append(re.sub(r"~{3,}", " | ", re.sub(r"[^\x20-\x7e]", "~", seg)))
        out.append("-" * 90)
        n += 1
        if n >= limit:
            break
    out.append("")


# ModelConfig struct fields (these are what model_list returns / needs)
ctx(r"ModelConfig\] Received config_name", 400, 400, 1, "ModelConfig fields")

# the get_model_list request/response log
ctx(r"get_model_list resp", 500, 500, 1, "get_model_list resp")

# llm_raw_chat request body
ctx(r"llm_raw_chat_custom_model request", 300, 700, 1, "llm_raw_chat request")

# request struct for the RPC (user_info/client_info/common_params confirmed from JS)
ctx(r"raw_chat_function", 250, 500, 2, "raw_chat_function")

out.append("")
out.append("=== all field-ish identifiers near 'prompt_set' ===")
i = txt.find("prompt_set")
if i > 0:
    seg = txt[max(0, i - 800):i + 800]
    toks = re.findall(r"[a-z][a-z0-9_]{4,34}", seg)
    seen = []
    for t in toks:
        if t not in seen:
            seen.append(t)
    out.append("  " + ", ".join(seen))

io.open("logs/_shapes.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
