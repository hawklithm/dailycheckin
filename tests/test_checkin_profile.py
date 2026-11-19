"""Offline checks of the installed native request configuration and sent bytes."""
import json
import sqlite3
import sys
import types

import httpx
import pytest

from trae2api import client_metadata
from trae2api.checkin import Account, checkin, main
from trae2api.checkin_profile import CheckinProfile, _read_jsonc, validate_base_url


@pytest.fixture
def installation(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    product = app / "product.json"
    product.write_text(json.dumps({"appVersion": "3.4.88", "nameShort": "Trae CN",
        "enableTelemetry": True, "bootConfig": {"ug": {"trae": {"normal": "https://ug.example"}}}}))
    (app / "package.json").write_text(json.dumps({"version": "1.108.9"}))
    directory = tmp_path / "native"
    (directory / "User/globalStorage").mkdir(parents=True)
    monkeypatch.setenv("TRAE2API_PRODUCT_JSON", str(product))
    monkeypatch.setenv("TRAE2API_USER_DATA", str(directory))
    return directory


def test_sent_request_uses_editor_version_ua_and_current_system_not_legacy_metadata(installation, tmp_path, monkeypatch):
    monkeypatch.setattr("trae2api.checkin.os_metadata", lambda: ("windows", "Windows 10 Education"))
    monkeypatch.setattr("trae2api.checkin.device_model", lambda: "Actual Model")
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"auth": {"token": "synthetic-token"}, "device": {
        "deviceId": "original-device", "osInfo": "Windows", "osVersion": "Windows 10",
        "deviceModel": "user-defined-label", "clientVersion": "3.4.4"}}))
    before = path.read_bytes()
    account = Account.from_file(path)
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"enable": True, "checked_in": False})
    with httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "python-test"}) as client:
        checkin(account, client, status_only=True)
    request = seen[0]
    assert str(request.url) == "https://ug.example/trae/api/v2/ug/checkin_credits/status"
    assert request.content == b'{"req_source":1}'
    assert request.headers["user-agent"] == "VSCode 1.108.9 (Trae CN)"
    assert request.headers["x-market-client-id"] == "VSCode 1.108.9"
    assert request.headers["x-app-version"] == "3.4.88"
    assert request.headers["x-device-type"] == "windows"
    assert request.headers["x-os-version"] == "Windows 10 Education"
    assert request.headers["x-device-brand"] == "Actual Model"
    assert request.headers["x-user-region"] == "CN"
    assert request.headers["authorization"] == "Cloud-IDE-JWT synthetic-token"
    assert request.headers["x-device-id"] == "original-device"
    assert path.read_bytes() == before


def test_session_environment_and_existing_native_machine_ids_are_reused_read_only(installation):
    settings = installation / "User/settings.json"
    settings.write_text('''{
      // Native marketplace + wrapper settings
      "ai_assistant.request.env": "ppe",
      "ai_assistant.request.ppe": "test-lane",
      "ai_assistant.request.envLane": "test-env-lane",
      "telemetry.telemetryLevel": "all",
    }''')
    database = installation / "User/globalStorage/state.vscdb"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        connection.executemany("INSERT INTO ItemTable VALUES (?,?)", [
            ("storage.serviceMachineId", "existing-service-id"),
            ("telemetry.machineId", "existing-telemetry-id")])
    before = database.read_bytes()
    profile = CheckinProfile.load()
    headers = dict(profile.headers)
    assert headers == {"x-use-ppe": "1", "x-tt-env": "test-lane", "x-env-lane": "test-env-lane",
                       "X-Market-User-Id": "existing-service-id", "VSCode-SessionId": "existing-telemetry-id"}
    assert database.read_bytes() == before
    assert not (installation / "machineid").exists()


@pytest.mark.parametrize("setting", [
    {"telemetry.telemetryLevel": "off"},
    {"telemetry.telemetryLevel": "error"},
    {"telemetry.enableTelemetry": False},
    {"telemetry.enableCrashReporter": False},
])
def test_marketplace_identity_headers_respect_native_telemetry_gate(installation, setting):
    (installation / "User/settings.json").write_text(json.dumps(setting))
    (installation / "machineid").write_text("00112233-4455-6677-8899-aabbccddeeff")
    assert "X-Market-User-Id" not in dict(CheckinProfile.load().headers)


def test_service_machine_id_file_fallback_does_not_create_new_identity(installation):
    assert dict(CheckinProfile.load().headers) == {}
    assert not (installation / "machineid").exists()
    (installation / "machineid").write_text("00112233-4455-6677-8899-aabbccddeeff")
    (installation / "User/globalStorage/storage.json").write_text(json.dumps({"telemetry.machineId": "native-session"}))
    headers = dict(CheckinProfile.load().headers)
    assert headers["X-Market-User-Id"] == "00112233-4455-6677-8899-aabbccddeeff"
    assert headers["VSCode-SessionId"] == "native-session"


def test_jsonc_comments_do_not_damage_urls_or_quoted_comment_markers(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{/* comment */"url":"https://example/a//b", "text":"/*not a comment*/",}')
    assert _read_jsonc(path) == {"url": "https://example/a//b", "text": "/*not a comment*/"}


def test_windows_metadata_matches_native_case_and_product_edition(monkeypatch):
    fake = types.SimpleNamespace(HKEY_LOCAL_MACHINE=object())
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    fake.OpenKey = lambda *args: Key()
    fake.QueryValueEx = lambda key, name: ("Windows 10 Education", 1)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(client_metadata.platform, "system", lambda: "Windows")
    assert client_metadata.os_metadata() == ("windows", "Windows 10 Education")


def test_cli_observed_region_and_runtime_origin_override_do_not_claim(installation, tmp_path, monkeypatch):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"auth": {"token": "synthetic"}, "device": {"deviceId": "original"}}))
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"enable": True, "checked_in": False})
    original_client = httpx.Client
    def mock_client(**kwargs):
        return original_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr("trae2api.checkin.httpx.Client", mock_client)
    assert main(["--creds", str(path), "--status-only", "--base-url", "https://runtime.example",
                 "--user-region", "SG"]) == 0
    assert len(seen) == 1
    assert seen[0].url.host == "runtime.example"
    assert seen[0].headers["x-user-region"] == "SG"
    assert seen[0].headers["user-agent"] == "VSCode 1.108.9 (Trae CN)"


@pytest.mark.parametrize("url", ["http://example", "https://user:pass@example", "https://example/path", "https://example?x=1"])
def test_invalid_api_origin_stops_before_credentials_can_be_sent(url):
    with pytest.raises(ValueError, match="HTTPS origin"):
        validate_base_url(url)
