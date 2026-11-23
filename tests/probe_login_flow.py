"""The Free-account theory is WRONG. Find the real difference instead.

Evidence that kills the entitlement theory:
  * real client logs: 90 successful LLM turns (rs_18_llm_response_first_token,
    rs_19_llm_response_done), ZERO quota/credit/upgrade signals
  * restrictedModelKeys is EMPTY -> no model is blocked for this account
  * enableSoloBuilder / enableSoloCoder are BOTH true

So a Free account does get agent-mode output on the real client. Our 4011 must
come from something else. The remaining candidate is the LOGIN FLOW - the user
explicitly pointed at it.

What the login flow could give us that we lack:
  * a different token (scope/audience) than the Cloud-IDE-JWT we mint
  * a session/connect token bound to the chat, issued by /api/ide/v1/connect
  * a refresh of iCubeServerData (the entitlement snapshot we just read)

This script compares the JWT we send against what the client's own flow
produces, and inspects the JWT claims for scope/audience.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def b64url_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def decode_jwt(tok: str) -> dict:
    parts = tok.split(".")
    out = {"_parts": len(parts)}
    if len(parts) >= 2:
        try:
            out["header"] = json.loads(b64url_decode(parts[0]))
        except Exception as e:  # noqa: BLE001
            out["header_error"] = str(e)
        try:
            out["payload"] = json.loads(b64url_decode(parts[1]))
        except Exception as e:  # noqa: BLE001
            out["payload_error"] = str(e)
    return out


async def main() -> int:
    from trae2api.auth import TraeAuth
    from trae2api.gateway import TraeGateway
    import httpx

    auth = TraeAuth()
    auth.load()
    jwt = auth.get_jwt()

    log("=" * 74)
    log("A. the Cloud-IDE-JWT we send - decoded")
    log("=" * 74)
    d = decode_jwt(jwt)
    log("header : " + json.dumps(d.get("header"), ensure_ascii=False))
    pl = d.get("payload") or {}
    log("payload:")
    for k, v in pl.items():
        s = str(v)
        if len(s) > 100:
            s = s[:100] + "..."
        log(f"    {k:24} = {s}")

    log("\n  --- scope/audience/role-ish claims ---")
    interesting = ("scope", "aud", "audience", "role", "perm", "entitle",
                   "product", "app", "client", "sub", "iss", "type", "plan")
    for k, v in pl.items():
        if any(t in k.lower() for t in interesting):
            log(f"    {k:24} = {v}")

    log("\n" + "=" * 74)
    log("B. credentials the client stores (what login produced)")
    log("=" * 74)
    c = auth.creds
    for f in ("token", "refresh_token", "user_id", "region", "host"):
        v = getattr(c, f, None)
        if v is None:
            continue
        s = str(v)
        log(f"  {f:16} len={len(s):5} head={s[:24]}")

    # does the stored token itself look like a JWT with richer claims?
    tok = getattr(c, "token", "") or ""
    if tok.count(".") == 2:
        log("\n  stored token IS a JWT - decoding:")
        dd = decode_jwt(tok)
        log("  header : " + json.dumps(dd.get("header"), ensure_ascii=False))
        for k, v in (dd.get("payload") or {}).items():
            s = str(v)
            if len(s) > 80:
                s = s[:80] + "..."
            log(f"    {k:22} = {s}")
    else:
        log(f"\n  stored token is opaque (len {len(tok)}), not a JWT")

    log("\n" + "=" * 74)
    log("C. compare against the real client's own header dump")
    log("=" * 74)
    log("  From completion.log the client sends:")
    log("    Authorization: Cloud-IDE-JWT ******")
    log("    x-ide-token  : ******")
    log("  i.e. the SAME two token headers we send. Let's verify our JWT is")
    log("  accepted by a cheap authenticated endpoint that mirrors the chat.")

    gw = TraeGateway(auth)
    H = gw._headers()
    async with httpx.AsyncClient(timeout=30) as cl:
        for path in ("/api/ide/v1/ping",
                     "/api/ide/v1/tenant/get_tenant_user_config",
                     "/api/v1/commercial/chat_mode"):
            try:
                r = await cl.post(f"{gw.base}{path}", json={}, headers=H)
                log(f"  {path:46} -> {r.status_code} "
                    f"{' '.join(r.text.split())[:120]}")
            except Exception as e:  # noqa: BLE001
                log(f"  {path:46} -> ERR {e}")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_jwt_claims.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
