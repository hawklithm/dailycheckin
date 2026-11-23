"""Rebuild trae2api credentials from Trae's own storage.json (3.4.7)."""
from __future__ import annotations

import base64
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
    raw = data["iCubeAuthInfo://icube.cloudide"]
    log.append(f"storage.json ok, cloudide blob len={len(raw)}")

    dec = None
    for fn in ("decrypt_blob", "decrypt_value"):
        f = getattr(cd, fn, None)
        if f is None:
            continue
        try:
            out = f(raw)
            log.append(f"{fn} -> {type(out).__name__}")
            if isinstance(out, dict):
                dec = out
                break
            elif isinstance(out, (bytes, bytearray)):
                dec = json.loads(out.decode("utf-8", "replace"))
                break
            elif isinstance(out, str):
                dec = json.loads(out)
                break
        except Exception as e:  # noqa: BLE001
            log.append(f"{fn} failed: {type(e).__name__}: {e}")
    if dec is None:
        # maybe the value is plain base64 of json
        try:
            dec = json.loads(base64.b64decode(raw + "=="))
            log.append("plain b64 json ok")
        except Exception as e:
            log.append(f"b64 failed: {e}")

    if not isinstance(dec, dict):
        log.append("could not decode cloudide blob")
        io.open("logs/_recreds.txt", "w", encoding="utf-8").write("\n".join(log))
        print("\n".join(log))
        return 1

    log.append("decoded keys: " + ", ".join(sorted(dec)))

    # the device keypair lives under iCubeAuthInfo://icube-dc:<deviceId>
    dev_id = dec.get("deviceId") or dec.get("device_id") or "4333646823299987"
    dev_blob = data.get(f"iCubeAuthInfo://icube-dc:{dev_id}")
    priv = pub = None
    if dev_blob:
        for fn in ("decrypt_blob", "decrypt_value"):
            f = getattr(cd, fn, None)
            if f is None:
                continue
            try:
                d2 = f(dev_blob)
                if isinstance(d2, (bytes, bytearray)):
                    d2 = json.loads(d2.decode("utf-8", "replace"))
                if isinstance(d2, dict):
                    priv = d2.get("privateKeyPEM") or d2.get("privateKey")
                    pub = d2.get("publicKeyPEM") or d2.get("publicKey")
                    if priv:
                        break
            except Exception:  # noqa: BLE001
                pass

    creds = {
        "auth": {
            "token": dec.get("token", ""),
            "refreshToken": dec.get("refreshToken", ""),
            "expiredAt": dec.get("expiredAt"),
            "refreshExpiredAt": dec.get("refreshExpiredAt"),
            "userId": dec.get("userId"),
            "host": dec.get("host", "https://api.trae.cn"),
            "userRegion": dec.get("userRegion", "CN"),
            "deviceId": dec.get("deviceId") or dev_id,
            "machineId": dec.get("machineId"),
            "privateKeyPEM": priv,
            "publicKeyPEM": pub,
            "account": dec.get("account"),
        }
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(creds, ensure_ascii=False, indent=2), encoding="utf-8")
    log.append(f"wrote {OUT}")
    log.append(f"  token len={len(creds['auth']['token'])}")
    log.append(f"  refreshToken len={len(creds['auth']['refreshToken'])}")
    log.append(f"  privateKey: {'yes' if priv else 'NO'}")
    log.append(f"  userId={creds['auth']['userId']} host={creds['auth']['host']}")

    io.open("logs/_recreds.txt", "w", encoding="utf-8").write("\n".join(log))
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
