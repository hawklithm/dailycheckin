"""Find the exact JSON/protobuf field names the llm_raw_chat endpoint parses.

Approach: the Rust handler for the endpoint must deserialize a struct. Look for
the struct's field names in the string table near 'llm_raw_chat', and look for
serde field-name attributes. Also check the harness.dll which has the same
endpoints and may hold the request type.
"""
import io
import re
import sys

FILES = [
    (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
     r"\resources\app\modules\ai-agent\ai_agent.dll", "ai_agent.dll"),
    (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
     r"\resources\app\modules\ai-agent\harness.dll", "harness.dll"),
]
out = []

for path, name in FILES:
    try:
        txt = open(path, "rb").read().decode("latin-1")
    except Exception as e:  # noqa: BLE001
        out.append(f"### {name}: FAILED {e}")
        continue
    out.append(f"### {name} ({len(txt)/1e6:.0f} MB)")

    # find where the endpoint string lives and dump the surrounding identifiers
    for m in list(re.finditer(r"api/ide/v2/llm_raw_chat", txt))[:1]:
        s = m.start()
        seg = txt[max(0, s - 1200):s + 1500]
        toks = re.findall(r"[a-z][a-z0-9_]{3,36}", seg)
        seen, ordered = set(), []
        for t in toks:
            if t not in seen:
                seen.add(t)
                ordered.append(t)
        out.append("  identifiers around the endpoint:")
        out.append("    " + ", ".join(ordered))

    # candidate request field names for a chat call
    out.append("")
    out.append("  field-name presence:")
    for f in ["user_input", "chat_history", "message_content", "model_name",
              "custom_model", "agent_type", "scene_location", "session_id",
              "message_id", "agent_id", "chat_session_id", "chat_message_id",
              "workspace_folders", "mention_context", "parsed_query",
              "code_selections", "active_text_editor", "multi_media",
              "reasoning_effort", "prompt_set", "config_name", "ab_version",
              "raw_chat_function", "function_type", "chat_type", "trigger_type",
              "operation_id", "channel_id", "stream", "request_id",
              "user_info", "common_params", "client_info", "data"]:
        n = len(re.findall(re.escape(f), txt))
        if n:
            out.append(f"    {f:<22} {n}")
    out.append("")

io.open("logs/_fields.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
