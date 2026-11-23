"""Confirm: api/v1/chat/* are LOCAL ai-server routes, not remote HTTP.

Evidence chain so far:
  * POST {gateway}/api/v1/chat/* -> 404 for all 9 routes
  * harness.dll contains "chat.start_chat/api/v1/chat/start_chatstart_chat"
    i.e. RPC-name / local-route / event-name triples
  * harness.dll is the ai-server process (a LOCAL node service)

So api/v1/chat/* is the route table of the local ai-server's OWN HTTP server,
which the renderer/sidecar talk to over loopback. That is a third hop, distinct
from:
  hop1  renderer --mojo--> sidecar
  hop2  sidecar/ai-server --HTTPS--> trae-api-cn.mchost.guru
  hop3  renderer --HTTP loopback--> ai-server   <-- api/v1/chat/*

If hop3 is a local HTTP server, it may be listening on a port we can reach.
Earlier notes said sidecar does not listen on 40005; but ai-server is a
DIFFERENT process. Let's enumerate listening ports owned by Trae processes.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    log("=" * 74)
    log("A. Trae processes")
    log("=" * 74)
    try:
        import psutil
    except ImportError:
        log("  psutil missing")
        return 1

    trae_pids = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (p.info.get("name") or "")
            if "trae" in name.lower():
                cmd = " ".join(p.info.get("cmdline") or [])
                kind = "main"
                for marker in ("process-type=ai-server",
                               "process-type=ai",
                               "utility-sub-type=node.mojom"):
                    if marker in cmd:
                        kind = marker.split("=")[-1]
                        break
                trae_pids.append((p.info["pid"], name, kind, cmd[:200]))
        except Exception:  # noqa: BLE001
            continue

    for pid, name, kind, cmd in sorted(trae_pids):
        log(f"  pid={pid:<7} kind={kind:<28} {name}")
        log(f"      {cmd}")

    log("\n" + "=" * 74)
    log("B. LISTENING ports owned by those PIDs")
    log("=" * 74)
    pidset = {pid for pid, _, _, _ in trae_pids}
    found = []
    try:
        conns = psutil.net_connections(kind="inet")
    except Exception as e:  # noqa: BLE001
        log(f"  net_connections failed: {e}")
        conns = []
    for c in conns:
        try:
            if c.status == "LISTEN" and c.pid in pidset:
                laddr = c.laddr
                addr = f"{laddr.ip}:{laddr.port}" if hasattr(
                    laddr, "ip") else str(laddr)
                found.append((c.pid, addr))
        except Exception:  # noqa: BLE001
            continue
    if found:
        for pid, addr in sorted(found, key=lambda t: t[1]):
            log(f"  pid={pid:<7} LISTEN {addr}")
    else:
        log("  (no listening sockets owned by Trae processes)")

    log("\n" + "=" * 74)
    log("C. raw netstat fallback (loopback LISTEN)")
    log("=" * 74)
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=30).stdout
        for line in out.splitlines():
            if "LISTENING" not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                pid = int(parts[-1])
            except ValueError:
                continue
            if pid in pidset:
                log(f"  {parts[1]:28} pid={pid}")
    except Exception as e:  # noqa: BLE001
        log(f"  netstat failed: {e}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_ports.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
