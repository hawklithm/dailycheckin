"""Read the sidecar's local SQLite cache to learn the real config keys.

The sidecar writes the model config it receives into
  %ICUBE_MODULAR_DATA_DIR%\\ai-agent\\database.db  -> table `model_config_cache`
keyed by (user_id, env, function). That table is the server-side source of
`2001 failed to get app config: record not found`, so its rows are the ground
truth for what `function` values the backend actually serves.

We copy the DB first (the running sidecar holds it open).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys

SRC = r"C:\Users\marcus\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db"
DST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "logs", "_agentdb_copy.db")

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def main() -> int:
    if not os.path.exists(SRC):
        log(f"!! source db missing: {SRC}")
        return 1
    shutil.copyfile(SRC, DST)
    con = sqlite3.connect(DST)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' order by name")]
    log(f"copied -> {DST}  ({os.path.getsize(DST)} bytes)")
    log(f"tables ({len(tables)}): {tables}\n")

    for name in tables:
        if not any(k in name for k in ("config", "model", "cache")):
            continue
        try:
            rows = con.execute(f'select * from "{name}"').fetchall()
        except Exception as e:  # noqa: BLE001
            log(f"### {name}: query failed {e}")
            continue
        log(f"### {name}  ({len(rows)} rows)")
        if not rows:
            continue
        log("    columns: " + ", ".join(rows[0].keys()))
        for r in rows[:40]:
            d = dict(r)
            cells = []
            for k, v in d.items():
                s = str(v)
                if isinstance(v, (bytes, bytearray)):
                    s = repr(v[:80])
                elif len(s) > 220:
                    s = s[:220] + "..."
                cells.append(f"{k}={s}")
            log("    - " + " | ".join(cells))
        log("")
    con.close()

    io.open(os.path.join(os.path.dirname(DST), "_agentdb.txt"), "w",
            encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
