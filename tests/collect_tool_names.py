"""Collect the tool names the model actually emits, from recent traces."""
import glob
import json
import os
import re
import sys


def main() -> None:
    files = sorted(glob.glob("trae2api/trace/*.jsonl"), key=os.path.getmtime, reverse=True)[:6]
    names = {}
    for f in files:
        try:
            lines = open(f, encoding="utf-8").readlines()
        except Exception:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("kind") != "sse_raw":
                continue
            data = rec["data"]
            if "FunctionCallBegin" not in data:
                continue
            for m in re.finditer(r'"name"\s*:\s*"([A-Za-z0-9_]+)"', data):
                names[m.group(1)] = names.get(m.group(1), 0) + 1
    sys.stdout.buffer.write((json.dumps(names, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
