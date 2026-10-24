"""Read-only auth verification against api.trae.cn (no token rotation triggered)."""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

sys.path.insert(0, r"D:\workspace\trae2api\trae2api")

STORAGE = r"C:\Users\marcus\AppData\Roaming\Trae CN\User\globalStorage\storage.json"


def load_creds() -> dict:
    from credential_decrypt import decrypt_value
    j = json.load(open(STORAGE, encoding="utf-8"))
    plain = decrypt_value(j["iCubeAuthInfo://icube.cloudide"])
    return json.loads(plain)


def post(url: str, token: str, body: dict, token_header: str = "x-cloudide-token") -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            token_header: token,
            "User-Agent": "trae-cn/3.4.4",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:2000]
    except Exception as e:
        return -1, str(e)


if __name__ == "__main__":
    creds = load_creds()
    print("userId:", creds["userId"], "| host:", creds["host"], "| region:", creds["userRegion"])
    print("token expires:", creds["expiredAt"], "| refresh expires:", creds["refreshExpiredAt"])
    print("token head:", creds["token"][:60], "...")
    host = creds["host"]

    code, body = post(
        f"{host}/cloudide/api/v3/trae/CheckLogin",
        creds["token"],
        {"IDEVersion": "3.4.4", "ReqSource": "IDE", "GetAIPayHost": True},
    )
    print(f"\n=== CheckLogin [{code}] ===")
    print(body[:1200])

    code, body = post(
        f"{host}/cloudide/api/v3/trae/GetUserInfo",
        creds["token"],
        {"ReqSource": "IDE", "IDEVersion": "3.4.4"},
    )
    print(f"\n=== GetUserInfo [{code}] ===")
    print(body[:1500])
