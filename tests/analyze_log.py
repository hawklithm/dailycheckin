"""Analyse the newest debug log: what the model asked for vs what we executed."""
import glob
import json
import os
import sys


def main() -> None:
    files = sorted(glob.glob(r"D:\workspace\trae2api\logs\debug-*.log"),
                   key=os.path.getmtime, reverse=True)
    if not files:
        print("no debug log")
        return
    f = files[0]
    print(f"log: {f}")
    records = []
    for line in open(f, encoding="utf-8", errors="replace"):
        try:
            records.append(json.loads(line))
        except Exception:
            pass
    print(f"records: {len(records)}")
    # show the tool-call / tool-executed pairs from the last session window
    last_request_ts = None
    for rec in records:
        if rec.get("kind") == "client_request":
            last_request_ts = rec.get("ts")
    print(f"\n--- last client_request at ts={last_request_ts} ---")
    shown = 0
    for rec in records:
        if rec.get("kind") not in ("tool_calls_received", "tool_executed",
                                   "client_response", "workspace_detected"):
            continue
        if shown >= 14:
            break
        kind = rec["kind"]
        if kind == "tool_calls_received":
            names = [c.get("name") for c in rec.get("calls", [])]
            print(f"  tool_calls_received  names={names}")
            for c in rec.get("calls", []):
                args = c.get("arguments")
                if isinstance(args, str) and len(args) > 200:
                    args = args[:200] + "..."
                print(f"      args={args}")
        elif kind == "tool_executed":
            res = (rec.get("result") or "")
            print(f"  tool_executed       name={rec.get('name')} result={res[:160]!r}")
        elif kind == "workspace_detected":
            print(f"  workspace_detected  folders={rec.get('folders')}")
        elif kind == "client_response":
            print(f"  client_response     finish={rec.get('finish_reason')} "
                  f"content={str(rec.get('content'))[:120]!r}")
        shown += 1


if __name__ == "__main__":
    main()
