"""End-to-end check: does mitmdump intercept a real HTTPS request?

Starts the proxy on a private port, makes a request through it, and reports
what landed in the capture log. This proves the whole chain works before the
user has to drive Trae.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, r"D:\workspace\trae2api")

PORT = "8083"
LOG = r"D:\workspace\trae2api\logs\mitm-requests.jsonl"
CA = r"D:\mitmconf\mitmproxy-ca-cert.pem"

env = dict(os.environ)
env.update({
    "MITM_PORT": PORT,
    "MITM_RUN_SECONDS": "40",
    "MITM_OUT": LOG,
    "MITM_FLOW": r"D:\trae_test.flow",
    "PYTHONPATH": r"D:\workspace\trae2api\.mitm",
})

proc = subprocess.Popen(
    [sys.executable, r"D:\workspace\trae2api\tests\run_mitmdump.py"],
    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    time.sleep(7)
    print("--- proxy up, making requests ---")
    import httpx
    for label, verify in (("no-verify", False), ("ca-verify", CA)):
        try:
            r = httpx.get(f"http://127.0.0.1:{PORT}/__probe__", timeout=10)
            print(f"  [{label}] plain http -> {r.status_code}")
        except Exception as e:  # noqa: BLE001
            print(f"  [{label}] http err {type(e).__name__}")
        try:
            with httpx.Client(verify=verify, trust_env=False,
                              proxy=f"http://127.0.0.1:{PORT}",
                              timeout=25) as c:
                r = c.get("https://api.trae.cn/api/v1/user")
                print(f"  [{label}] https -> {r.status_code} {r.text[:100]!r}")
        except Exception as e:  # noqa: BLE001
            print(f"  [{label}] https err {type(e).__name__}: {str(e)[:140]}")
    time.sleep(3)
finally:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=10)
    except Exception:
        proc.kill()
        out, _ = proc.communicate()

print("\n--- mitmdump output ---")
print(out[-1500:])

print("\n--- capture log ---")
if os.path.exists(LOG):
    with open(LOG, encoding="utf-8") as f:
        lines = f.readlines()
    print(f"{len(lines)} records")
    for l in lines[-6:]:
        import json
        try:
            r = json.loads(l)
            print(f"  {r.get('kind')} {r.get('method','')} {r.get('host','')}{r.get('path','')}"
                  f" status={r.get('status','')} body={len(r.get('body') or '')}b")
        except Exception:
            print("  " + l[:120])
else:
    print("no log")
