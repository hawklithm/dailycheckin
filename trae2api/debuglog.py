"""Debug logging for trae2api.

TRAE2API_DEBUG=1 turns on verbose, human-readable logging of the whole
conversation: the OpenAI request we received, the exact gateway body we sent,
the raw SSE events, the tool calls we executed and their results, and the
final response we returned.

Output goes to both the console and logs/debug-<date>.log (JSON-lines, one
record per line, so it is easy to grep or replay).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
_ENABLED = os.environ.get("TRAE2API_DEBUG") == "1"
_logger: logging.Logger | None = None
_file_handler: logging.Handler | None = None


def enabled() -> bool:
    return _ENABLED


def get_logger() -> logging.Logger:
    global _logger, _file_handler
    if _logger is not None:
        return _logger
    _logger = logging.getLogger("trae2api.debug")
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False
    if not _logger.handlers:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("[trae2api] %(message)s"))
        _logger.addHandler(sh)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            path = LOG_DIR / f"debug-{time.strftime('%Y%m%d')}.log"
            _file_handler = logging.FileHandler(path, encoding="utf-8")
            _file_handler.setFormatter(logging.Formatter("%(message)s"))
            _logger.addHandler(_file_handler)
        except Exception:
            _file_handler = None
    return _logger


def record(kind: str, **fields) -> None:
    """Write one structured record (no-op unless TRAE2API_DEBUG=1)."""
    if not _ENABLED:
        return
    rec = {"ts": round(time.time(), 3), "kind": kind}
    rec.update(fields)
    try:
        line = json.dumps(rec, ensure_ascii=False, default=str)
    except Exception:
        line = json.dumps({"ts": rec["ts"], "kind": kind, "error": "unserializable"},
                          ensure_ascii=False)
    get_logger().info(line)


def text_of(content) -> str:
    """Flatten OpenAI message content (str or blocks) for logging."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, dict):
                if blk.get("type") == "text":
                    parts.append(str(blk.get("text", "")))
                elif blk.get("type") == "image_url":
                    parts.append("[image]")
                else:
                    parts.append(f"[{blk.get('type', 'block')}]")
            else:
                parts.append(str(blk))
        return "\n".join(parts)
    return str(content)
