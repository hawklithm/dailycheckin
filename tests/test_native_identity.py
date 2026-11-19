"""Synthetic native login/device evidence and request-time identity guards."""
import base64
import json

import httpx
import pytest

from trae2api.checkin import Account, CheckinError, checkin, main
from trae2api.native_identity import NativeIdentity, NativeIdentityError


@pytest.fixture
def native(tmp_path, monkeypatch):
    root = tmp_path / "native"
    (root / "User/globalStorage").mkdir(parents=True)
    session = root / "logs/20261120T000000"
    session.mkdir(parents=True)
    storage = root / "User/globalStorage/storage.json"
    auth = {"userId": "synthetic-user", "token": "native-test-token", "account": {"scope": "marscode"}}
    storage.write_text(json.dumps({"iCubeAuthInfo://icube.cloudide": "encoded:" + json.dumps(auth),
                                   "iCubeAuthInfo://icube-dc:remote-test-device": "private-key-not-read"}))
    (session / "main.log").write_text(
        "[ICDRS] (init) resolve rdid: remote-test-device\n"
        "[ICDRS] (init) initialization done, did: remote-test-device, ldid: local-test-device, rdid: remote-test-device\n"
        'getStoreRegion {"region":"CN"}\n')
    monkeypatch.setenv("TRAE2API_USER_DATA", str(root))
    monkeypatch.setattr("trae2api.native_identity.decrypt_value", lambda value: value.removeprefix("encoded:"))
    return root, storage, session / "main.log"


def update_auth(storage, **changes):
    raw = json.loads(storage.read_text())
    auth = json.loads(raw["iCubeAuthInfo://icube.cloudide"].removeprefix("encoded:"))
    auth.update(changes)
    raw["iCubeAuthInfo://icube.cloudide"] = "encoded:" + json.dumps(auth)
    storage.write_text(json.dumps(raw))


def test_native_source_sends_native_token_and_verified_remote_id_without_writes(native):
    root, storage, log = native
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    account = Account.from_native()
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"enable": True, "checked_in": False})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        checkin(account, client, status_only=True)
    assert seen[0].headers["authorization"] == "Cloud-IDE-JWT native-test-token"
    assert seen[0].headers["x-device-id"] == "remote-test-device"
    assert seen[0].headers["x-user-region"] == "CN"
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert "native-test-token" not in repr(account)
    assert "remote-test-device" not in repr(account.native_identity)


def test_does_not_use_arbitrary_other_oauth_key_when_log_key_missing(native):
    root, storage, log = native
    raw = json.loads(storage.read_text())
    raw["iCubeAuthInfo://icube-dc:another-device"] = raw.pop("iCubeAuthInfo://icube-dc:remote-test-device")
    storage.write_text(json.dumps(raw))
    with pytest.raises(NativeIdentityError, match="does not match"):
        Account.from_native()


def test_newest_incomplete_session_does_not_fall_back_to_old_device(native):
    root, storage, log = native
    newest = root / "logs/20261120T010000"
    newest.mkdir()
    (newest / "main.log").write_text("initializing")
    with pytest.raises(NativeIdentityError, match="no completed"):
        Account.from_native()


def test_rejects_local_fallback(native):
    root, storage, log = native
    log.write_text(log.read_text().replace("local-test-device", "remote-test-device"))
    with pytest.raises(NativeIdentityError, match="local fallback"):
        Account.from_native()


def test_late_resolution_after_native_timeout_updates_remote_device(native):
    root, storage, log = native
    log.write_text(
        "[ICDRS] (init) initialization done, did: local-test-device, ldid: local-test-device, rdid: 0\n"
        "[ICDRS] (init) resolve rdid: remote-test-device\n"
        'getStoreRegion {"region":"CN"}\n')
    assert Account.from_native().device_id == "remote-test-device"


@pytest.mark.parametrize("changed", [{"token": "changed-token"}, {"userId": "changed-account"}])
def test_account_or_token_change_after_status_stops_before_claim(native, changed):
    root, storage, log = native
    account = Account.from_native()
    seen = []
    def handler(request):
        seen.append(request.url.path)
        update_auth(storage, **changed)
        return httpx.Response(200, json={"enable": True, "checked_in": False})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CheckinError, match="claim failed:.*changed"):
            checkin(account, client)
    assert seen == ["/trae/api/v2/ug/checkin_credits/status"]


def test_device_change_after_status_stops_before_claim(native):
    root, storage, log = native
    account = Account.from_native()
    seen = []
    def handler(request):
        seen.append(request.url.path)
        log.write_text(log.read_text().replace("remote-test-device", "new-remote-device"))
        raw = json.loads(storage.read_text())
        raw["iCubeAuthInfo://icube-dc:new-remote-device"] = "not-read"
        storage.write_text(json.dumps(raw))
        return httpx.Response(200, json={"enable": True, "checked_in": False})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CheckinError, match="claim failed:.*changed"):
            checkin(account, client)
    assert seen == ["/trae/api/v2/ug/checkin_credits/status"]


def test_invalid_native_scope_is_rejected(native):
    root, storage, log = native
    update_auth(storage, account={"scope": "saas"})
    with pytest.raises(NativeIdentityError, match="marscode"):
        Account.from_native()


def test_expired_native_token_has_native_relogin_instruction(native, monkeypatch):
    root, storage, log = native
    payload = base64.urlsafe_b64encode(b'{"exp":100}').decode().rstrip("=")
    update_auth(storage, token=f"header.{payload}.signature")
    monkeypatch.setattr("trae2api.checkin.time.time", lambda: 200)
    with pytest.raises(NativeIdentityError, match="sign in to Trae CN"):
        Account.from_native()


def test_native_dry_run_does_not_read_login(monkeypatch):
    def unexpected():
        raise AssertionError("must not read credentials in dry run")
    monkeypatch.setattr("trae2api.checkin.NativeIdentity.load", unexpected)
    assert main(["--native"]) == 0


def test_native_cli_status_only_uses_native_source(native, monkeypatch):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"enable": True, "checked_in": False})
    client_class = httpx.Client
    monkeypatch.setattr("trae2api.checkin.httpx.Client",
                        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    assert main(["--native", "--status-only"]) == 0
    assert len(seen) == 1
    assert seen[0].headers["x-device-id"] == "remote-test-device"
