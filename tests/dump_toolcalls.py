"""Dump the FULL tool-call payload from the newest trace that contains one."""
import glob
import json
import os
import re
import sys


def main() -> None:
    files = sorted(glob.glob("trae2api/trace/*.jsonl"), key=os.path.getmtime, reverse=True)[:4]
    for f in files:
        # reassemble the response text across output events
        parts = []
        has_call = False
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("kind") != "sse_raw":
                continue
            data = rec["data"]
            m = re.search(r'"response":"((?:[^"\\]|\\.)*)"', data)
            if not m:
                continue
            try:
                text = json.loads('"' + m.group(1) + '"')
            except Exception:
                continue
            if "FunctionCallBegin" in text:
                has_call = True
            parts.append(text)
        if not has_call:
            continue
        full = "".join(parts)
        sys.stdout.buffer.write((f"== {os.path.basename(f)} ==\n").encode())
        for m in re.finditer(r"<\|FunctionCallBegin\|>(.*?)<\|FunctionCallEnd\|>", full, re.DOTALL):
            sys.stdout.buffer.write(m.group(0).encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
        # also show the request body's tools (if the client declared any)
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("kind") == "request":
                body = rec["data"].get("body", {})
                sys.stdout.buffer.write(("agent_type=%s scene=%s user_input=%s\n" % (
                    body.get("agent_type"), body.get("scene_location"),
                    json.dumps(body.get("user_input", ""), ensure_ascii=False)[:200])).encode())
                break
        print()


if __name__ == "__main__":
    main()
