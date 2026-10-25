"""Show the agent_type/scene of the newest gateway_body record."""
import glob
import json
import os
import sys


def main() -> None:
    files = sorted(glob.glob(r"D:\workspace\trae2api\logs\debug-*.log"),
                   key=os.path.getmtime, reverse=True)
    for f in files:
        last = None
        for line in open(f, encoding="utf-8", errors="replace"):
            if '"gateway_body"' not in line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            last = rec
        if last:
            b = last.get("body", {})
            sys.stdout.buffer.write(json.dumps({
                "file": os.path.basename(f),
                "agent_type": b.get("agent_type"),
                "scene_location": b.get("scene_location"),
                "agent": b.get("agent"),
            }, ensure_ascii=False).encode("utf-8") + b"\n")
            return
    print("no gateway_body record found")


if __name__ == "__main__":
    main()
