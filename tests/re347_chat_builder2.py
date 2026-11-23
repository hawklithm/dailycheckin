"""Locate the renderer's real chat request object.

The previous hunt found only one concrete request shape in workbench.js:
    {service:"context", method:"slash_list",
     data:{agent_type:"solo_agent", builtin_skill_names:["run"]}}
so requests are built via a generic helper rather than a literal
service:"chat" object we can grep. This searches for the structural markers of
the chat request instead: its distinctive data fields.
"""
from __future__ import annotations

import io
import os
import re
import sys

WB = (r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
      r"\resources\app\out\vs\workbench\workbench.desktop.main.js")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    if not os.path.exists(WB):
        log(f"!! missing {WB}")
        return 1
    with io.open(WB, "rb") as f:
        txt = f.read().decode("latin-1")
    log(f"workbench.js {len(txt)} chars\n")

    # distinctive fields we know the V1 chat body carries
    targets = [
        "agent_process_support", "chat_process_version", "scene_location",
        "message_content", "text_content", "parsed_query", "user_input",
        "model_auto_selection", "builtin_skill_names", "slash_list",
        "workspace_folders", "code_selections", "mention_context",
        "chat_history", "native_function_call", "hook_event_name",
    ]
    log("=== occurrences of key chat-request fields ===")
    for t in targets:
        n = txt.count(t)
        log(f"  {t:26} x{n}")
        if n and n < 4000:
            m = re.search(re.escape(t), txt)
            if m:
                seg = txt[max(0, m.start() - 260):m.start() + 520]
                log("      " + re.sub(r"\s+", " ", seg)[:1100])
    log("")
    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_chatbuilder2.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
