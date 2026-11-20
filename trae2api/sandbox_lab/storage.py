"""Bound all experimental files to the repository's isolated lab directory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


WORKSPACE = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = WORKSPACE / "logs" / "sandbox-device-lab"


def confined(path: Path | str) -> Path:
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("lab paths must not contain parent traversal")
    target = (path if path.is_absolute() else WORKSPACE / path).resolve()
    # Do not resolve OUTPUT_ROOT: a junction redirecting that root outside the
    # workspace must be rejected too, rather than becoming a new trusted root.
    if target != OUTPUT_ROOT and OUTPUT_ROOT not in target.parents:
        raise ValueError("output must remain inside logs/sandbox-device-lab")
    return target


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def atomic_json(path: Path, value: dict, *, create_only: bool = False) -> None:
    target = confined(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = confined(target)
    fd, name = tempfile.mkstemp(prefix=".lab-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
        confined(target)
        if create_only:
            try:
                os.link(name, target)
            except FileExistsError:
                pass  # Load and validate the winner; never overwrite a profile.
        else:
            os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path) -> dict:
    target = confined(path)
    if target.stat().st_size > 64 * 1024:
        raise ValueError("lab document exceeds size limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("invalid persisted lab document") from None
    if not isinstance(value, dict):
        raise ValueError("lab document must be an object")
    return value
