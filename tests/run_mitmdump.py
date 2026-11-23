"""Start mitmdump programmatically (no console script needed).

Writes a heartbeat line so the caller can tell it actually started, and stops
after N seconds when RUN_SECONDS is set.
"""
import os
import sys
import threading
import time

os.environ.setdefault("PYTHONPATH", r"D:\workspace\trae2api\.mitm")
sys.path.insert(0, r"D:\workspace\trae2api\.mitm")
sys.path.insert(0, r"D:\workspace\trae2api")

PORT = os.environ.get("MITM_PORT", "8081")
CONF = os.environ.get("MITM_CONF", r"D:\mitmconf")
OUT_LOG = os.environ.get("MITM_OUT",
                         r"D:\workspace\trae2api\logs\mitm-requests.jsonl")
FLOW = os.environ.get("MITM_FLOW", r"D:\trae_capture.flow")
RUN_SECONDS = float(os.environ.get("MITM_RUN_SECONDS", "0"))


def main() -> int:
    from mitmproxy.tools import main as mmain

    argv = [
        "mitmdump",
        "--listen-host", "127.0.0.1",
        "--listen-port", PORT,
        "--set", f"confdir={CONF}",
        "--set", "flow_detail=0",
        "--no-http2",
        "-s", r"D:\workspace\trae2api\tests\mitm_dump.py",
        "-w", FLOW,
    ]
    print(f"starting mitmdump on 127.0.0.1:{PORT}", flush=True)

    def stop_later():
        if RUN_SECONDS <= 0:
            return
        time.sleep(RUN_SECONDS)
        print(f"\n[MITM] stopping after {RUN_SECONDS}s", flush=True)
        os._exit(0)

    if RUN_SECONDS > 0:
        threading.Thread(target=stop_later, daemon=True).start()

    old = sys.argv
    sys.argv = argv
    try:
        mmain.mitmdump()
    except SystemExit as e:
        print(f"[MITM] exited code={e.code}", flush=True)
        return int(e.code or 0)
    except Exception as e:  # noqa: BLE001
        print(f"[MITM] ERROR {type(e).__name__}: {e}", flush=True)
        return 1
    finally:
        sys.argv = old


if __name__ == "__main__":
    sys.exit(main())
