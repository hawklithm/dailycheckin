"""Trae CN IDE check-in, based on the locally installed client's code.

Only sends requests when explicitly invoked. The supplied device ID is an
opaque client identifier, not a proven replacement for device registration.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import base64
import json
from pathlib import Path
import time
from typing import Any

import httpx
from .client_metadata import clean_model, client_version, device_model, os_metadata
from .checkin_profile import CheckinProfile, validate_base_url
from .native_identity import NativeIdentity, NativeIdentityError

BASE_URL = "https://api.trae.cn"
STATUS_PATH = "/trae/api/v2/ug/checkin_credits/status"
CLAIM_PATH = "/trae/api/v2/ug/checkin_credits/claim"


@dataclass(frozen=True)
class Account:
    token: str = field(repr=False)
    device_id: str = field(repr=False)
    device_brand: str = ""
    device_type: str = ""
    os_version: str = ""
    app_version: str = ""
    editor_version: str = "1.107.1"
    client_name: str = "Trae CN"
    user_region: str = "CN"
    base_url: str = BASE_URL
    session_headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    native_identity: NativeIdentity | None = field(default=None, repr=False)

    @classmethod
    def from_native(cls) -> "Account":
        identity = NativeIdentity.load()
        try:
            _reject_expired_token(identity.token)
        except ValueError:
            raise NativeIdentityError("native login token expired; sign in to Trae CN again") from None
        profile = CheckinProfile.load()
        os_name, os_version = os_metadata()
        return cls(token=identity.token, device_id=identity.device_id,
                   device_brand=device_model(), device_type=os_name, os_version=os_version,
                   app_version=client_version("3.4.20"), editor_version=profile.editor_version,
                   client_name=profile.client_name, user_region=identity.user_region,
                   base_url=profile.base_url, session_headers=profile.headers,
                   native_identity=identity)

    @classmethod
    def from_file(cls, path: str | Path) -> "Account":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("credentials must be a JSON object")
        auth, device = data.get("auth", data), data.get("device", {})
        if not isinstance(auth, dict) or not isinstance(device, dict):
            raise ValueError("credentials auth and device must be JSON objects")
        token = auth.get("token") or auth.get("jwt")
        # Older credential exports keep the device fields inside auth.
        # An explicit deviceId takes precedence, even if invalid: do not
        # silently substitute a different identity in that case.
        if "deviceId" not in device:
            device = auth
        device_id = device.get("deviceId")
        if not isinstance(token, str) or not token or not isinstance(device_id, str) or not device_id or device_id == "0":
            raise ValueError("credentials must contain auth.token (or auth.jwt) and device.deviceId (or legacy auth.deviceId)")
        _reject_expired_token(token)
        model = device_model() or device.get("deviceModel") or device.get("deviceBrand") or ""
        # Older login code stored the user-chosen device name as its model.
        if not model or model == device.get("deviceName"):
            model = device_model()
        os_name, os_version = os_metadata()
        profile = CheckinProfile.load()
        return cls(token=token, device_id=device_id, device_brand=clean_model(model),
                   device_type=os_name, os_version=os_version,
                   app_version=client_version(device.get("clientVersion") or "3.4.20"),
                   editor_version=profile.editor_version, client_name=profile.client_name,
                   user_region="CN", base_url=profile.base_url, session_headers=profile.headers)

    def headers(self) -> dict[str, str]:
        result = {"Authorization": f"Cloud-IDE-JWT {self.token}",
                  "Content-Type": "application/json", "x-device-id": self.device_id,
                  "x-rust-request-timeout": "30000",
                  "User-Agent": f"VSCode {self.editor_version} ({self.client_name})",
                  "X-Market-Client-Id": f"VSCode {self.editor_version}",
                  "X-User-Region": self.user_region}
        result.update(self.session_headers)
        for key, value in (("x-device-brand", self.device_brand),
                           ("x-device-type", self.device_type),
                           ("x-os-version", self.os_version),
                           ("x-app-version", self.app_version)):
            if value:
                result[key] = value
        return result


class CheckinError(Exception):
    pass


def _reject_expired_token(token: str) -> None:
    """Use a JWT expiry only for a local diagnostic, not authentication."""
    parts = token.split(".")
    if len(parts) != 3:
        return
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        expiry = payload.get("exp") if isinstance(payload, dict) else None
    except (ValueError, UnicodeError):
        return
    if type(expiry) in (int, float) and expiry <= time.time():
        raise ValueError("login token expired; run `python -m trae2api login`, then retry check-in")


def _post(client: httpx.Client, path: str, account: Account) -> dict[str, Any]:
    try:
        if account.native_identity is not None:
            try:
                account.native_identity.ensure_current()
            except NativeIdentityError as exc:
                raise CheckinError(str(exc)) from None
        response = client.post(account.base_url + path, content=b'{"req_source":1}',
                               headers=account.headers(), follow_redirects=False)
        if response.status_code != 200:
            raise CheckinError(f"HTTP {response.status_code}; outcome may be unknown")
        try:
            body = response.json()
        except ValueError as exc:
            raise CheckinError("invalid JSON response; outcome may be unknown") from exc
    except httpx.HTTPError as exc:
        raise CheckinError(f"network error ({type(exc).__name__}); outcome may be unknown") from exc
    if not isinstance(body, dict):
        raise CheckinError("invalid response object; outcome may be unknown")
    if "code" in body:
        code = body["code"]
        if type(code) not in (int, float) or code != 0:
            message = next((body[k] for k in ("message", "msg", "error_message")
                            if isinstance(body.get(k), str) and body[k]), "")
            # Do not dump the response body or echo a credential in diagnostics.
            message = message.replace(account.token, "[redacted]")
            detail = f"; message={message[:500]!r}" if message else ""
            raise CheckinError(f"business or protocol error: code={code!r}{detail}")
    return body


def _read_status(account: Account, client: httpx.Client) -> dict[str, Any]:
    try:
        status = _post(client, STATUS_PATH, account)
    except CheckinError as exc:
        raise CheckinError(f"status query failed: {exc}") from exc
    enabled, checked = status.get("enable"), status.get("checked_in")
    if type(enabled) is not bool or type(checked) is not bool:
        raise CheckinError("status query failed: response missing boolean enable/checked_in")
    result = {"enable": enabled, "checked_in": checked, "credits": status.get("credits")}
    for key in ("did_checked_in", "extra_credits"):
        if key in status:
            result[key] = status[key]
    if "did_checked_in" in result and type(result["did_checked_in"]) is not bool:
        raise CheckinError("status query failed: did_checked_in must be boolean when present")
    return result


def checkin(account: Account, client: httpx.Client, *, status_only: bool = False) -> dict[str, Any]:
    """Query, claim once if eligible, then verify status without retrying claim."""
    status = _read_status(account, client)
    if status_only:
        return {"action": "status", **status}
    if status["checked_in"] or status.get("did_checked_in") is True:
        return {"action": "already_checked_in", "credits": status.get("credits")}
    if not status["enable"]:
        return {"action": "disabled", "credits": status.get("credits")}
    try:
        _post(client, CLAIM_PATH, account)
    except CheckinError as exc:
        raise CheckinError(f"claim failed: {exc}") from exc
    result = {"action": "claim_accepted", "credits": status.get("credits"), "verified": False}
    try:
        after = _read_status(account, client)
    except CheckinError as exc:
        # A failed confirmation must not cause a second claim.
        result["verification_error"] = str(exc)
        return result
    result["status"] = after
    if after["checked_in"] or after.get("did_checked_in") is True:
        result.update(action="checked_in", verified=True)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Trae CN IDE check-in")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--creds", help="explicit independent credentials JSON file")
    source.add_argument("--native", action="store_true", help="read the native login and corroborated remote device ID")
    parser.add_argument("--base-url", help="override the installed ug API HTTPS origin")
    parser.add_argument("--user-region", help="override the CN store region header with an observed native value")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="send status and, if eligible, claim")
    mode.add_argument("--status-only", action="store_true", help="query status without claiming credits")
    args = parser.parse_args(argv)
    if not args.execute and not args.status_only:
        print("Dry run: no credentials read and no requests sent. Add --execute or --status-only to run.")
        return 0
    try:
        account = Account.from_native() if args.native else Account.from_file(args.creds)
        if args.base_url:
            account = replace(account, base_url=validate_base_url(args.base_url))
        if args.user_region is not None:
            account = replace(account, user_region=args.user_region)
        with httpx.Client(timeout=30, trust_env=False) as client:
            result = checkin(account, client, status_only=args.status_only)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (CheckinError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Check-in failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
