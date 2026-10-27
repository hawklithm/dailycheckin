"""Complete the handler table and recover the CHAT call chain ordering.

Previous pass got 10 handlers/77 methods but missed the most important ones
(AgentHandler, LiteHandler, HubHandler, DocsetHandler, CKGHandler, ...) because
their "start ... handler" log string differs.

More importantly, this pass targets the CALL CHAIN: for one LLM request, what
is called in what order. Sources:
  * log strings that announce each stage, in binary order
  * source paths under src/domain/ (the service layer)
  * the ChatHandler / ChatService stage messages

Binary order of log strings roughly follows source order, and the strings
themselves name the stages, so harvesting them in order reconstructs the flow.
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
DLL = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def split_snake(run: str) -> list[str]:
    parts = re.split(r"(?=(?:get|set|create|update|delete|remove|add|list|"
                     r"batch|prefetch|connect|save|sync|stop|start|send|"
                     r"query|check|report|commit|apply|generate|fetch|"
                     r"register|install|enable|disable|revert|pin|fork|"
                     r"clean|clear|search|open|close|run|read|write|upload|"
                     r"download|import|export|switch|move|copy|rename|"
                     r"notify|poll|wait|call|cancel|confirm|reject|approve|"
                     r"deny|chat|stop|resume|retry|update)_)", run)
    out = []
    for p in parts:
        p = p.strip("_")
        if len(p) > 3 and "_" in p and not p.isdigit():
            out.append(p)
    return out


def main() -> int:
    with io.open(DLL, "rb") as f:
        buf = f.read()

    # ---- 1. every handler, wherever it appears ---------------------------
    log("=" * 74)
    log("1. ALL HANDLER NAME OCCURRENCES + following method run")
    log("=" * 74)
    found: dict[str, list[str]] = {}
    for m in re.finditer(rb"\[([A-Za-z]{3,30}Handler)\]", buf):
        handler = m.group(1).decode("ascii", "replace")
        after = buf[m.end():m.end() + 700]
        txt = re.sub(rb"[^\x20-\x7e]+", b" ", after).decode("ascii", "replace")
        ms = split_snake(txt)
        if ms:
            cur = found.setdefault(handler, [])
            for x in ms:
                if x not in cur:
                    cur.append(x)
    for h in sorted(found):
        log(f"\n### {h} ({len(found[h])})")
        log("    " + "  ".join(found[h][:40]))

    # ---- 2. chat stage log strings, in binary order ----------------------
    log("\n" + "=" * 74)
    log("2. CHAT STAGE LOG STRINGS (binary order ~ source order)")
    log("=" * 74)
    stage_re = re.compile(
        rb"\[(ChatService|ChatHandler|ModelService|LLMAdapter|ChatContext|"
        rb"ChatStream|MessageService|ModelMgr|model mgr|ChatTurn|"
        rb"create_agent_task|do_create_cloud_agent_task)\]"
        rb"[ -~]{0,120}")
    seen = set()
    for m in stage_re.finditer(buf):
        s = m.group(0).decode("ascii", "replace")
        if s in seen:
            continue
        seen.add(s)
        log(f"  @{m.start():>10}  {s[:150]}")

    # ---- 3. domain source paths (module map) -----------------------------
    log("\n" + "=" * 74)
    log("3. DOMAIN / INFRASTRUCTURE SOURCE PATHS")
    log("=" * 74)
    sp = re.compile(rb"apps\\icube_server_rs\\modules\\ai-agent\\src\\"
                    rb"([a-z0-9_\\/]+\.rs)")
    paths = sorted({m.group(1).decode("ascii", "replace")
                    for m in sp.finditer(buf)})
    for p in paths:
        log(f"    src\\{p}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_callchain_raw.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:24000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
