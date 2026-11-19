import base64
import json

import httpx
import pytest

from trae2api.checkin import Account, CheckinError, CLAIM_PATH, STATUS_PATH, checkin, main


@pytest.fixture(autouse=True)
def isolated_native_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAE2API_USER_DATA", str(tmp_path / "native-user-data"))


def run_with_replies(replies):
    seen = []

    def handler(request):
        seen.append(request)
        return replies[len(seen) - 1]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return client, seen


def test_status_then_claim():
    client, seen = run_with_replies([
        httpx.Response(200, json={"enable": True, "checked_in": False, "credits": 10}),
        httpx.Response(200, json={"code": 0}),
        httpx.Response(200, json={"enable": True, "checked_in": True, "credits": 10}),
    ])
    with client:
        result = checkin(Account("fake-token", "fake-device"), client)
        assert result["action"] == "checked_in"
        assert result["verified"] is True
    assert [r.url.path for r in seen] == [STATUS_PATH, CLAIM_PATH, STATUS_PATH]
    for r in seen:
        assert json.loads(r.content) == {"req_source": 1}
        assert r.headers["authorization"] == "Cloud-IDE-JWT fake-token"
        assert r.headers["x-device-id"] == "fake-device"
        assert r.headers["x-rust-request-timeout"] == "30000"
        assert r.headers["user-agent"] == "VSCode 1.107.1 (Trae CN)"
        assert r.headers["x-market-client-id"] == "VSCode 1.107.1"
        assert r.headers["x-user-region"] == "CN"
        assert r.content == b'{"req_source":1}'


def test_status_only_does_not_claim_when_eligible():
    client, seen = run_with_replies([
        httpx.Response(200, json={"enable": True, "checked_in": False, "credits": 10}),
    ])
    with client:
        assert checkin(Account("token", "device"), client, status_only=True) == {
            "action": "status", "enable": True, "checked_in": False, "credits": 10}
    assert [r.url.path for r in seen] == [STATUS_PATH]


@pytest.mark.parametrize("stage", ["status query", "claim"])
def test_rejection_identifies_stage(stage):
    replies = []
    if stage == "claim":
        replies.append(httpx.Response(200, json={"enable": True, "checked_in": False}))
    replies.append(httpx.Response(200, json={"code": 9074, "msg": "try later"}))
    client, seen = run_with_replies(replies)
    with client, pytest.raises(CheckinError, match=f"{stage} failed:.*9074"):
        checkin(Account("token", "device"), client)
    assert len(seen) == len(replies)


@pytest.mark.parametrize("body,action", [
    ({"enable": True, "checked_in": True}, "already_checked_in"),
    ({"enable": False, "checked_in": False}, "disabled"),
    ({"enable": True, "checked_in": False, "did_checked_in": True}, "already_checked_in"),
])
def test_skip_claim(body, action):
    client, seen = run_with_replies([httpx.Response(200, json=body)])
    with client:
        assert checkin(Account("token", "device"), client)["action"] == action
    assert len(seen) == 1


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"enable": True}),
    httpx.Response(200, json={"enable": True, "checked_in": False, "code": 9102}),
    httpx.Response(200, text="invalid"),
    httpx.Response(401, json={}),
])
def test_status_failures_do_not_claim(response):
    client, seen = run_with_replies([response])
    with client, pytest.raises(CheckinError):
        checkin(Account("token", "device"), client)
    assert len(seen) == 1


def test_claim_failure_is_not_retried():
    client, seen = run_with_replies([
        httpx.Response(200, json={"enable": True, "checked_in": False}),
        httpx.Response(429, json={}),
    ])
    with client, pytest.raises(CheckinError):
        checkin(Account("token", "device"), client)
    assert len(seen) == 2


def test_dry_run_never_reads_credentials(tmp_path):
    assert main(["--creds", str(tmp_path / "missing.json")]) == 0


def test_credentials_file(tmp_path):
    path = tmp_path / "account.json"
    path.write_text(json.dumps({"auth": {"token": "t"}, "device": {"deviceId": "d"}}))
    account = Account.from_file(path)
    assert (account.token, account.device_id) == ("t", "d")
    assert account.app_version


def test_legacy_credentials_file(tmp_path):
    path = tmp_path / "account.json"
    path.write_text(json.dumps({"auth": {"token": "t", "deviceId": "legacy-device"}}))
    account = Account.from_file(path)
    assert (account.token, account.device_id) == ("t", "legacy-device")


@pytest.mark.parametrize("reply", [
    httpx.Response(200, json={"enable": True, "checked_in": False}),
    httpx.Response(503),
])
def test_claim_accepted_but_not_confirmed_does_not_retry(reply):
    client, seen = run_with_replies([
        httpx.Response(200, json={"enable": True, "checked_in": False}),
        httpx.Response(200, json={"code": 0}),
        reply,
    ])
    with client:
        result = checkin(Account("token", "device"), client)
    assert result["action"] == "claim_accepted"
    assert result["verified"] is False
    assert [r.url.path for r in seen] == [STATUS_PATH, CLAIM_PATH, STATUS_PATH]


def test_status_retains_optional_fields():
    body = {"enable": True, "checked_in": False, "did_checked_in": True, "extra_credits": 50}
    client, seen = run_with_replies([httpx.Response(200, json=body)])
    with client:
        result = checkin(Account("token", "device"), client, status_only=True)
    assert result["did_checked_in"] is True
    assert result["extra_credits"] == 50
    assert len(seen) == 1


def test_confirmation_timeout_keeps_claim_accepted_without_retry():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if len(seen) == 1:
            return httpx.Response(200, json={"enable": True, "checked_in": False})
        if len(seen) == 2:
            return httpx.Response(200, json={"code": 0})
        raise httpx.ReadTimeout("timeout", request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = checkin(Account("token", "device"), client)
    assert result["action"] == "claim_accepted"
    assert result["verified"] is False
    assert "ReadTimeout" in result["verification_error"]
    assert seen == [STATUS_PATH, CLAIM_PATH, STATUS_PATH]


def test_legacy_metadata_is_completed_without_changing_identity(tmp_path, monkeypatch):
    monkeypatch.setattr("trae2api.checkin.client_version", lambda fallback: "3.4.20")
    monkeypatch.setattr("trae2api.checkin.device_model", lambda: "Actual Model\x00")
    path = tmp_path / "account.json"
    payload = {"auth": {"token": "t"}, "device": {
        "deviceId": "original", "deviceName": "custom", "deviceModel": "custom", "deviceBrand": "custom"}}
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    account = Account.from_file(path)
    assert account.device_id == "original"
    assert account.headers()["x-app-version"] == "3.4.20"
    assert account.headers()["x-device-brand"] == "Actual Model"
    assert path.read_bytes() == before


def test_expired_token_is_rejected_before_network(tmp_path, monkeypatch):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 100}).encode()).decode().rstrip("=")
    path = tmp_path / "account.json"
    path.write_text(json.dumps({"auth": {"token": f"header.{payload}.signature", "deviceId": "d"}}))
    monkeypatch.setattr("trae2api.checkin.time.time", lambda: 200)
    with pytest.raises(ValueError, match="login token expired"):
        Account.from_file(path)


def test_business_error_includes_message_without_echoing_token():
    client, seen = run_with_replies([
        httpx.Response(200, json={"code": 1001, "message": "invalid secret-token"}),
    ])
    with client, pytest.raises(CheckinError) as error:
        checkin(Account("secret-token", "device"), client)
    assert "invalid [redacted]" in str(error.value)
    assert "secret-token" not in str(error.value)
    assert len(seen) == 1


@pytest.mark.parametrize("device_id", ["current-device", "", "0", None])
def test_explicit_device_identity_takes_precedence(tmp_path, device_id):
    path = tmp_path / "account.json"
    path.write_text(json.dumps({"auth": {"token": "t", "deviceId": "legacy-device"},
                                "device": {"deviceId": device_id}}))
    if device_id == "current-device":
        assert Account.from_file(path).device_id == "current-device"
    else:
        with pytest.raises(ValueError):
            Account.from_file(path)
