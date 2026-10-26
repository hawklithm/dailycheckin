"""Test whether /api/ide/v1/chat accepts the REAL catalog model names.

Earlier notes recorded "4023 model unknown" for every name tried - but those
were names from OUR local catalog (e.g. deepseek-v4.1-flash, glm-5.3-flash,
Doubao-Seed-2.1-Turbo). /api/ide/v1/providers just returned the real catalog
and the names differ:
    ours: deepseek-v4.1-flash   real: deepseek-v4-flash
    ours: Doubao-Seed-2.1-Turbo real: doubao-seed-2-1-turbo-260628

If V1 accepts the real names, "model is always 豆包" is fixed immediately,
without needing llm_raw_chat at all.

gateway.py: TRAE2API_MODEL forces model_name, TRAE2API_PASSTHROUGH_MODEL=1
passes the caller's model through.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROBE_PATH = os.path.join(HERE, "_v1_model_runner.py")
OUT_LOG = os.path.join(ROOT, "logs", "_v1models.txt")

PROBE = r'''
import asyncio, os, re, sys, uuid
sys.path.insert(0, r"D:\workspace\trae2api")
from trae2api.auth import TraeAuth
from trae2api.gateway import TraeGateway

async def main():
    a = TraeAuth(); a.load()
    g = TraeGateway(a)
    chunks = []
    try:
        async for raw in g.stream_chat(
                model=os.environ["TRAE2API_MODEL"],
                messages=[{"role": "user", "content": "reply with the single word OK"}],
                session_id=str(uuid.uuid4())):
            chunks.append(raw)
            if len(chunks) > 50:
                break
    except Exception as e:
        print("EXC", type(e).__name__, str(e)[:200])
        return
    txt = b"".join(chunks).decode("utf-8", "replace")
    if "4023" in txt:
        print("RESULT 4023 unknown-model")
    elif '"response"' in txt:
        outs = re.findall(r'"response"\s*:\s*"((?:[^"\\]|\\.){0,80})', txt)
        print("RESULT OK", "|".join(outs[:5])[:200])
    else:
        m = re.search(r'"message"\s*:\s*"([^"]{0,140})', txt)
        print("RESULT ERR", m.group(1) if m else txt[:200])

asyncio.run(main())
'''

# real names straight from /api/ide/v1/providers
CANDIDATES = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "doubao-seed-2-1-turbo-260628",
    "doubao-seed-2-1-pro-260628",
    "glm-5.3",
    "kimi-k3",
    "minimax-m3",
    "qwen3.8-max",
    "doubao-seed-evolving",
]


def main() -> int:
    with io.open(PROBE_PATH, "w", encoding="utf-8") as f:
        f.write(PROBE)

    out = []
    for name in CANDIDATES:
        env = dict(os.environ)
        env["TRAE2API_MODEL"] = name
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            r = subprocess.run([sys.executable, PROBE_PATH], env=env,
                               capture_output=True, timeout=150, cwd=ROOT)
            txt = (r.stdout or b"").decode("utf-8", "replace")
            err = (r.stderr or b"").decode("utf-8", "replace")
            lines = [l for l in txt.splitlines() if l.strip()]
            line = lines[-1] if lines else (err[:150] or "(no output)")
            out.append(f"  {name:32} {line[:170]}")
        except subprocess.TimeoutExpired:
            out.append(f"  {name:32} TIMEOUT")
        except Exception as e:  # noqa: BLE001
            out.append(f"  {name:32} ERR {type(e).__name__}: {e}")

    res = "\n".join(out)
    io.open(OUT_LOG, "w", encoding="utf-8").write(res)
    print(res)
    try:
        os.remove(PROBE_PATH)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
