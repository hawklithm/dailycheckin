"""Pull the plaintext chat-core traffic out of Trae's renderer logs.

The previous scan showed window*/renderer.log carries a `[trae-chat-core]`
prefix with rich JSON: [MetadataHandler] received metadata, Session fetched,
RealtimeEventService. That component sits right where the model/request is
decided, so its lines can carry model_name / config_name / function keys that
the black-box probes could not guess.

This dump keeps whole lines (not truncated) for the chat-core records so the
JSON can actually be read.
"""
from __future__ import annotations

import io
import os
import re
import sys

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
ROOT = os.path.join(APPDATA, "Trae CN")

PREFIXES = ["[trae-chat-core]", "[MetadataHandler]", "RealtimeEventService",
            "iCubeAgentService", "[LLMAdapter]", "chat-core"]

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


KEYWORDS = re.compile(
    "model_name|config_name|model_config|raw_chat_function|function|"
    "prompt_set|llm_raw|billing|usage|metering|reasoning", re.I)


def main() -> int:
    hits: dict[str, list[str]] = {}
    # prefer the newest sessions, they match the installed 3.4.7
    sessions = []
    logs_dir = os.path.join(ROOT, "logs")
    if os.path.isdir(logs_dir):
        sessions = sorted(
            (d for d in os.listdir(logs_dir)
             if os.path.isdir(os.path.join(logs_dir, d))),
            reverse=True)
    files = []
    for s in sessions:
        base = os.path.join(logs_dir, s)
        for b, _d, fs in os.walk(base):
            for fn in fs:
                if fn.lower().endswith((".log", ".1.log", ".txt")):
                    files.append(os.path.join(b, fn))

    for p in files:
        try:
            if os.path.getsize(p) > 200 * 1024 * 1024:
                continue
            with io.open(p, "rb") as f:
                if b"\x00" in f.read(4096):
                    continue
            with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:  # noqa: BLE001
            continue
        for ln in lines:
            if not any(pre in ln for pre in PREFIXES):
                continue
            if not KEYWORDS.search(ln):
                continue
            hits.setdefault(p, []).append(ln.rstrip("\n"))

    total = 0
    for p in sorted(hits, key=lambda k: -len(hits[k])):
        rel = p.replace(ROOT, "")
        log(f"\n########## {rel}  ({len(hits[p])} lines)")
        for ln in hits[p][:30]:
            total += 1
            log(ln[:3000])
    log(f"\n==== total {total} lines across {len(hits)} files")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_chatcore.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
