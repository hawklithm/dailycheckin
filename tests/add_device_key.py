"""Add the ECDSA device keypair (from storage.json) to the rebuilt credentials."""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api import credential_decrypt as cd  # noqa: E402

STORAGE = pathlib.Path(
    r"C:\Users\marcus\AppData\Roaming\Trae CN\User\globalStorage\storage.json")
OUT = pathlib.Path(__file__).resolve().parent.parent / "trae2api" / "trae2api.json"

log: list[str] = []


def main() -> int:
    data = json.loads(STORAGE.read_text(encoding="utf-8"))
    dev_id = "4333646823299987"
    dev = cd.decrypt_value(data[f"iCubeAuthInfo://icube-dc:{dev_id}"])
    if isinstance(dev, str):
        dev = json.loads(dev)

    creds = json.loads(OUT.read_text(encoding="utf-8"))
    creds["auth"]["privateKeyPEM"] = dev["privateKeyPEM"]
    creds["auth"]["publicKeyPEM"] = dev["publicKeyPEM"]
    creds["auth"]["deviceId"] = dev_id
    OUT.write_text(json.dumps(creds, ensure_ascii=False, indent=2), encoding="utf-8")
    log.append(f"updated {OUT}")
    log.append("  privateKeyPEM: yes")
    log.append("  publicKeyPEM:  yes")
    log.append("  deviceId:      " + dev_id)
    io.open("logs/_keyadd.txt", "w", encoding="utf-8").write("\n".join(log))
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
