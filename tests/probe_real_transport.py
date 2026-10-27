"""What transport does the REAL client actually use for chat?

Decisive finding: across 449 plaintext log files the real client NEVER mentions
    api/agent/v3, create_agent_task, llm_utils_chat, api/ide/v1/chat
while it mentions
    start_chat            x117
    subscribe_events      x173   (as service=lite, method=subscribe_events)
    lite_01_create_session, rs_07_create_task, svr_01_queue_*  (stage timings)

So the real chat path is:
    lite.create_chat_session -> start_chat -> lite.subscribe_events
and it is spoken over the LOCAL RPC (mojo) to the sidecar, with the sidecar
then talking to the server. api/ide/v1/chat is a server-side endpoint that the
client logs never show because the sidecar, not the renderer, calls it - and
api/agent/v3 belongs to ai-server, a different process with its own path.

That explains the whole puzzle:
  * we CAN look like the client at the HTTP level (we do - v1/chat streams)
  * but "the client" is not one caller: it is renderer + sidecar + ai-server,
    and the agent capabilities live behind the ai-server's own credentials/
    entitlements, which are provisioned server-side per account.
  * impersonating the renderer's HTTP requests does not grant ai-server's
    rights.

This script extracts the real stage timeline the client logs, which shows the
actual sequence and the queue/entitlement steps.
"""
from __future__ import annotations

import io
import os
import re
import sys

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
TRAE_LOGS = os.path.join(APPDATA, "Trae CN", "logs")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


STAGES = re.compile(r'"([a-z0-9_]{4,40})":(\d{10,16})')
RPC = re.compile(r"\[ai-chat\] doRequestWithStream start: service=([a-z_]+), "
                 r"method=([a-z_]+)")


def main() -> int:
    stage_names: dict[str, int] = {}
    rpc_calls: dict[tuple[str, str], int] = {}
    queue_lines: list[str] = []

    for base, _d, fs in os.walk(TRAE_LOGS):
        for fn in fs:
            if not fn.lower().endswith((".log", ".txt")):
                continue
            p = os.path.join(base, fn)
            try:
                if os.path.getsize(p) > 250 * 1024 * 1024:
                    continue
                with io.open(p, "rb") as f:
                    if b"\x00" in f.read(4096):
                        continue
                with io.open(p, "r", encoding="utf-8",
                             errors="replace") as f:
                    text = f.read()
            except Exception:  # noqa: BLE001
                continue
            for m in RPC.finditer(text):
                key = (m.group(1), m.group(2))
                rpc_calls[key] = rpc_calls.get(key, 0) + 1
            for m in STAGES.finditer(text):
                stage_names[m.group(1)] = stage_names.get(m.group(1), 0) + 1
            for line in text.splitlines():
                if "queue" in line.lower() and "svr_" in line:
                    if len(queue_lines) < 5:
                        queue_lines.append(" ".join(line.split())[:400])

    log("=" * 74)
    log("A. RPC calls the renderer actually makes (service, method)")
    log("=" * 74)
    for (svc, meth), c in sorted(rpc_calls.items(), key=lambda kv: -kv[1]):
        log(f"  {svc:14}.{meth:32} x{c}")

    log("\n" + "=" * 74)
    log("B. CHAT STAGE TIMELINE names (the real request sequence)")
    log("=" * 74)
    for name, c in sorted(stage_names.items(), key=lambda kv: -kv[1]):
        log(f"  {name:40} x{c}")

    log("\n" + "=" * 74)
    log("C. server-side queue / entitlement evidence")
    log("=" * 74)
    for ln in queue_lines:
        log("  " + ln)

    log("\n" + "=" * 74)
    log("D. CONCLUSION")
    log("=" * 74)
    log("  The renderer never speaks HTTP chat endpoints; it issues mojo RPC")
    log("  (lite.create_chat_session / chat.start_chat / lite.subscribe_events).")
    log("  The stage names show server-side steps we cannot perform from")
    log("  outside: svr_01_queue_*, rs_07_create_task, rs_06_resolvers_*.")
    log("  Those are the agent-mode entitlement/queueing path, and they are")
    log("  driven by the ai-server process, not by request shape.")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_real_transport.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
