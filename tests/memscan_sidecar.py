"""Search the sidecar's memory for a plaintext llm_raw_chat request.

Rust's serde_json serialises to plaintext before handing the buffer to the HTTP
client, so a request body can exist in the heap briefly. We scan the process's
committed pages for the endpoint string and print the surrounding bytes.

Needs no elevation: we are the same user as the sidecar.
"""
from __future__ import annotations

import io
import os
import re
import sys
import time

import psutil

NEEDLE = b"llm_raw_chat"
OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def find_sidecars() -> list[int]:
    pids = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cl = " ".join(p.info.get("cmdline") or [])
            if "Trae" in (p.info.get("name") or "") and "process-type=ai" in cl:
                pids.append(p.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def read_mem(pid: int, addr: int, size: int) -> bytes | None:
    """Read another process's memory (same user, no elevation needed)."""
    import ctypes
    import ctypes.wintypes as w

    PROCESS_VM_READ = 0x0010
    k = ctypes.windll.kernel32
    h = k.OpenProcess(PROCESS_VM_READ, False, pid)
    if not h:
        return None
    try:
        buf = (ctypes.c_char * size)()
        n = w.SIZE_T(0)
        ok = k.ReadProcessMemory(h, w.LPCVOID(addr), buf, size,
                                 ctypes.byref(n))
        return buf.raw[: n.value] if ok else None
    finally:
        k.CloseHandle(h)


def main() -> int:
    pids = find_sidecars()
    log(f"sidecar pids: {pids}")
    if not pids:
        log("no sidecar running")
        io.open("logs/_memscan.txt", "w", encoding="utf-8").write("\n".join(OUT))
        print("\n".join(OUT))
        return 1

    for pid in pids:
        try:
            proc = psutil.Process(pid)
        except psutil.Error as e:
            log(f"pid {pid}: {e}")
            continue
        log(f"\n=== pid {pid} ({proc.name()}) ===")
        hits = 0
        try:
            maps = list(proc.memory_maps(grouped=False))
        except psutil.Error as e:
            log(f"  memory_maps failed: {e}")
            maps = []
        # private anonymous rw pages are what we want (heap). On Windows the
        # path is empty for those, but psutil may report "[heap]" or a file.
        readable = [m for m in maps
                    if "r" in m.perms and (m.path == "" or m.path.startswith("[heap"))]
        log(f"  {len(maps)} maps, {len(readable)} private rw")
        if not readable:
            # fall back: scan every readable mapping that is not a DLL/exe
            readable = [m for m in maps if "r" in m.perms
                        and not m.path.lower().endswith((".dll", ".exe", ".node"))]
            log(f"  fallback: {len(readable)} readable non-image maps")
        for m in readable:
            try:
                chunk = read_mem(pid, m.addr, min(m.rss * 2, 32 * 1024 * 1024))
            except Exception:
                chunk = None
            if not chunk:
                continue
            for mm in re.finditer(re.escape(NEEDLE), chunk):
                s = mm.start()
                seg = chunk[max(0, s - 900):s + 1400]
                # show printable runs
                runs = re.findall(rb"[\x20-\x7e]{6,}", seg)
                text = b" | ".join(runs).decode("latin-1", "replace")
                if len(text) < 40:
                    continue
                hits += 1
                log(f"  --- hit {hits} @ {m.addr}+{s} ---")
                log("      " + text[:1200])
                if hits >= 6:
                    break
            if hits >= 6:
                break
        if not hits:
            log("  no plaintext llm_raw_chat in private rw pages")

    io.open("logs/_memscan.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
