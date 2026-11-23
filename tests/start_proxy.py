"""Start trae2api with the debug/exec switches on (single managed instance).

Usage:
    python tests\start_proxy.py            # start (kills any existing instance)
    python tests\start_proxy.py --stop     # stop only
"""
import os
import subprocess
import sys
import time
import urllib.request

REPO = r"D:\workspace\trae2api"
ENV = {
    "TRAE2API_EXEC_TOOLS": "1",   # bridge: execute the gateway's tools locally
    "TRAE2API_DEBUG": "1",        # verbose conversation log -> logs/debug-<date>.log
}


def find_pids() -> list[int]:
    """PIDs of running `python -m trae2api` processes."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*-m trae2api*' } | "
         "Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True, timeout=30)
    pids = []
    for tok in out.stdout.split():
        if tok.isdigit():
            pids.append(int(tok))
    return pids


def stop() -> None:
    for pid in find_pids():
        print(f"stopping trae2api pid {pid}")
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=30)
    time.sleep(2)


def start() -> None:
    stop()
    psi_env = os.environ.copy()
    psi_env.update(ENV)
    log_err = open(os.path.join(REPO, "notes", "server-err.log"), "a", encoding="utf-8")
    p = subprocess.Popen([sys.executable, "-m", "trae2api"], cwd=REPO, env=psi_env,
                         stdout=log_err, stderr=log_err,
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    print(f"started trae2api pid {p.pid}")
    for _ in range(20):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3) as r:
                print("health:", r.read().decode()[:120])
                return
        except Exception:
            continue
    print("WARNING: health check did not pass; see notes/server-err.log")


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop()
    else:
        start()
