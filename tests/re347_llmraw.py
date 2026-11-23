"""Focus: llm_raw_chat (v1/v2), model_list, and session usage in Trae 3.4.7."""
import io
import re

DLL = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
       r"\resources\app\modules\ai-agent\ai_agent.dll")
txt = open(DLL, "rb").read().decode("latin-1")
out = []


def ctx(pattern, width_before=260, width_after=420, limit=3):
    got = 0
    for m in re.finditer(pattern, txt):
        seg = txt[max(0, m.start() - width_before): m.start() + width_after]
        out.append(re.sub(r"~{3,}", " | ", re.sub(r"[^\x20-\x7e]", "~", seg)))
        out.append("-" * 100)
        got += 1
        if got >= limit:
            break


out.append("=== llm_raw_chat (the real LLM call!) ===")
ctx(r"llm_raw_chat", 300, 500, 4)

out.append("")
out.append("=== api/ide/v2/llm_raw_chat ===")
ctx(r"api/ide/v2/llm_raw_chat", 200, 300, 2)

out.append("")
out.append("=== model_list / get_model_list ===")
ctx(r"api/ide/v1/model_list", 200, 300, 2)
ctx(r"get_model_list", 200, 300, 2)

out.append("")
out.append("=== get_session_usage (billing!) ===")
ctx(r"get_session_usage", 200, 300, 2)

out.append("")
out.append("=== v2 paths (full list) ===")
v2 = sorted(set(m.group(0) for m in
                re.finditer(r"api/ide/v2/[a-z0-9_/\-]{2,50}", txt)))
for v in v2:
    out.append("  " + v)

io.open("logs/_llmraw347.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
