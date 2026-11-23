"""Search plaintext Trae logs for the real chat RPC body / config data.

Unlike the .alaudalog files (encrypted), these are plain text:
  <APPDATA>\\Trae CN\\logs\\<session>\\window1\\renderer.log
  <APPDATA>\\Trae CN\\logs\\<session>\\main.log
  <APPDATA>\\Trae CN\\logs\\<session>\\Modular\\cue-server_*_stdout.log

The renderer builds the full RPC envelope in convertReqToRustPayload before it
goes to the sidecar over mojo, so its log is the only place the real body can
appear in plaintext.
"""
from __future__ import annotations

import io
import os
import re
import sys

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
ROOT = os.path.join(APPDATA, "Trae CN")

NEEDLES = [
    "llm_raw_chat", "convertReqToRustPayload", "batch_get_detail_param",
    "raw_chat_function", "function_configs", "model_config",
    "config_name", "prompt_set", "keep_syncing_model_info",
    "get_model_list", "connect_model", "common_params",
    "streamlined_common_params", "model_name", "app config",
]

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def sniff(path: str) -> bool:
    """True if the file looks like plain text."""
    with io.open(path, "rb") as f:
        head = f.read(4096)
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except Exception:  # noqa: BLE001
        try:
            head.decode("gbk")
        except Exception:  # noqa: BLE001
            return False
    return True


def main() -> int:
    if not os.path.isdir(ROOT):
        log(f"!! {ROOT} missing")
        return 1
    pat = re.compile("|".join(re.escape(n) for n in NEEDLES), re.I)
    scanned = 0
    for base, _dirs, files in os.walk(ROOT):
        for fn in files:
            p = os.path.join(base, fn)
            if not fn.lower().endswith((".log", ".txt", ".json")):
                continue
            try:
                if os.path.getsize(p) > 120 * 1024 * 1024:
                    continue
                if not sniff(p):
                    continue
            except OSError:
                continue
            scanned += 1
            try:
                with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:  # noqa: BLE001
                continue
            hits = [ln.rstrip("\n") for ln in lines if pat.search(ln)]
            if not hits:
                continue
            rel = p.replace(ROOT, "")
            log(f"\n### {rel}   ({len(hits)} matching lines)")
            for ln in hits[:40]:
                log("   " + ln[:400])
    log(f"\nscanned {scanned} plain-text files")
    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_rendererlog.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
