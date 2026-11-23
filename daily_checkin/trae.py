"""Trae CN IDE check-in, based on the locally installed client's code.

Only sends requests when explicitly invoked. The supplied device ID is an
opaque client identifier, not a proven replacement for device registration.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import time
from typing import Any, Callable

import httpx
from buddy_agent_auth.providers.trae.client_metadata import clean_model, client_version, device_model, os_metadata
from .trae_profile import CheckinProfile, validate_base_url
from buddy_agent_auth.providers.trae.credentials import load_file, reject_expired_token as _reject_expired_token
from buddy_agent_auth.providers.trae import DeviceIdSource, NativeIdentity, NativeIdentityError, TraeNativeProvider

# Keep the source checkout fallback used by existing account/device data.
from buddy_agent_auth.providers.trae import app_storage as _storage
_storage.configure_fallback(Path(__file__).resolve().parent.parent)

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
    user_id: str = field(default="", repr=False)

    @classmethod
    def from_native(cls, *, device_id_source: DeviceIdSource = "get-device-id") -> "Account":
        identity = TraeNativeProvider(device_id_source=device_id_source).load()
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
                   native_identity=identity, user_id=identity.user_id)

    @classmethod
    def from_file(cls, path: str | Path) -> "Account":
        auth, device, token, device_id = load_file(path)
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
                   user_region="CN", base_url=profile.base_url, session_headers=profile.headers,
                   user_id=str(auth.get("userId") or ""))

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


def checkin(account: Account, client: httpx.Client, *, status_only: bool = False,
            before_claim: Callable[[], bool] | None = None,
            diagnostic: Callable[..., None] | None = None) -> dict[str, Any]:
    """Query, claim once if eligible, then verify status without retrying claim."""
    if account.native_identity is not None:
        try:
            account.native_identity.ensure_current()
        except NativeIdentityError as exc:
            raise CheckinError(str(exc)) from None
    if account.native_identity is None or getattr(account.native_identity, "device_id_source", "get-device-id") != "existing":
        from buddy_agent_auth.providers.trae.app_storage import resolve_pair
        try:
            device_id, hardware = resolve_pair(account.user_id, account.device_id, client, account.app_version)
        except Exception as exc:
            _report_failure(diagnostic, 'device_resolution', exc)
            raise
        account = replace(account, device_id=device_id)
        if hardware is not None:
            account = replace(account, device_brand=clean_model(hardware.model),
                              device_type=hardware.os_name, os_version=hardware.os_version)
    try:
        status = _read_status(account, client)
    except Exception as exc:
        _report_failure(diagnostic, 'status_query', exc)
        raise
    if status_only:
        return {"action": "status", **status}
    if status["checked_in"]:
        return {"action": "already_checked_in", "credits": status.get("credits")}
    if status.get("did_checked_in") is True:
        return {"action": "device_already_checked_in", "credits": status.get("credits"),
                "status": status}
    if not status["enable"]:
        return {"action": "disabled", "credits": status.get("credits")}
    if before_claim is not None and not before_claim():
        return {"action": "cancelled"}
    try:
        _post(client, CLAIM_PATH, account)
    except CheckinError as exc:
        _report_failure(diagnostic, 'claim', exc)
        raise CheckinError(f"claim failed: {exc}") from exc
    result = {"action": "claim_accepted", "credits": status.get("credits"), "verified": False}
    try:
        after = _read_status(account, client)
    except CheckinError as exc:
        _report_failure(diagnostic, 'claim_verification', exc)
        # A failed confirmation must not cause a second claim.
        result["verification_error"] = str(exc)
        return result
    result["status"] = after
    if after["checked_in"]:
        result.update(action="checked_in", verified=True)
    return result


def _report_failure(diagnostic, stage: str, exc: Exception) -> None:
    if diagnostic is None:
        return
    from .trae_diagnostics import safe_error_fields
    try:
        diagnostic(stage=stage, **safe_error_fields(exc))
    except Exception:
        pass  # Logging must not alter check-in behavior.


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Trae CN IDE check-in")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--creds", help="explicit independent credentials JSON file")
    source.add_argument("--native", action="store_true", help="read the account and token from the native client")
    parser.add_argument("--device-id-source", choices=["existing", "get-device-id"],
                        help="--native only: get-device-id (default) uses the account-bound device; "
                             "existing uses the native session device")
    parser.add_argument("--base-url", help="override the installed ug API HTTPS origin")
    parser.add_argument("--user-region", help="override the CN store region header with an observed native value")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="send status and, if eligible, claim")
    mode.add_argument("--status-only", action="store_true", help="query status without claiming credits")
    args = parser.parse_args(argv)
    if args.device_id_source is not None and not args.native:
        parser.error("--device-id-source requires --native")
    if not args.execute and not args.status_only:
        print("Dry run: no credentials read and no requests sent. Add --execute or --status-only to run.")
        return 0
    try:
        from buddy_agent_auth.providers.trae.app_storage import root
        root()
        account = (Account.from_native(device_id_source=args.device_id_source or "get-device-id")
                   if args.native else Account.from_file(args.creds))
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
