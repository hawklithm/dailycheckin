"""Extract every model_info / config_name Trae actually used, from the logs.

The renderer log holds [MetadataHandler] records whose user_message_context
carries a full `model_info` object straight out of a live chat. That gives us
the real (config_name, model_name, agent_type, reasoning_effort_level) tuples
we could never guess from outside - these are what batch_get_detail_param and
llm_raw_chat expect.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

APPDATA = os.environ.get("APPDATA", r"C:\Users\marcus\AppData\Roaming")
ROOT = os.path.join(APPDATA, "Trae CN")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brute_json(s: str, key: str):
    """Return every JSON object that starts at each `key":"` occurrence."""
    out = []
    for m in re.finditer(re.escape(key) + r'"\s*:\s*', s):
        i = s.find("{", m.end())
        if i < 0:
            continue
        depth = 0
        for j in range(i, len(s)):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    blob = s[i:j + 1]
                    try:
                        out.append(json.loads(blob))
                    except Exception:  # noqa: BLE001
                        pass
                    break
    return out


def main() -> int:
    logs_dir = os.path.join(ROOT, "logs")
    files = []
    for base, _d, fs in os.walk(logs_dir):
        for fn in fs:
            if fn.lower().endswith((".log", ".txt")):
                files.append(os.path.join(base, fn))

    models: dict[str, dict] = {}
    agents: dict[str, int] = {}
    extras: dict[str, int] = {}

    for p in files:
        try:
            if os.path.getsize(p) > 200 * 1024 * 1024:
                continue
            with io.open(p, "rb") as f:
                if b"\x00" in f.read(4096):
                    continue
            with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:  # noqa: BLE001
            continue
        for obj in brute_json(text, "model_info"):
            cn = obj.get("config_name") or obj.get("model_name")
            if not cn:
                continue
            models.setdefault(cn, obj)
        for obj in brute_json(text, "model_smart_selection_meta"):
            cn = obj.get("config_name")
            if cn:
                extras[cn] = extras.get(cn, 0) + 1
        for m in re.finditer(r'"agent_type"\s*:\s*"([^"]+)"', text):
            agents[m.group(1)] = agents.get(m.group(1), 0) + 1

    log("=== model_info objects recovered from plaintext logs ===")
    for cn, obj in sorted(models.items()):
        interesting = {k: v for k, v in obj.items()
                       if k in ("config_name", "model_name", "provider",
                                "is_preset", "config_source", "display_model_name",
                                "use_remote_service", "multimodal",
                                "prompt_max_tokens", "max_tokens", "max_turn",
                                "raw_chat_function", "prompt_set",
                                "context_window_sizes", "reasoning_effort_level",
                                "custom_model_type", "region", "auth_type")}
        log(f"\n--- {cn}")
        log("    " + json.dumps(interesting, ensure_ascii=False))

    log("\n=== agent_type values seen ===")
    for a, c in sorted(agents.items(), key=lambda kv: -kv[1]):
        log(f"    {a:24} x{c}")

    log("\n=== model_smart_selection_meta config_names ===")
    for cn, c in sorted(extras.items(), key=lambda kv: -kv[1]):
        log(f"    {cn:40} x{c}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_realmodelinfo.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
