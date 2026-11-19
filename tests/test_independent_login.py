"""Independent login integration with fake registration and OAuth endpoints."""
import gzip
import json
import struct
import sys

import httpx
import pytest

from trae2api.aha_registration import registration_request
from trae2api.device_hardware import Hardware, uuid_from_smbios
from trae2api.login import TraeLoginFlow, _iso_from_ms_or_iso
from trae2api.login_identity import IdentityStore
from trae2api.auth import TraeAuth


@pytest.fixture
def hardware(monkeypatch):
    value = Hardware("33221100-5544-7766-8899-AABBCCDDEEFF", "synthetic-serial", "Actual Model",
                     "Actual Manufacturer", "AMD Ryzen Synthetic", "windows", "Windows 10 Education", "10.0.19045", "00-11-22-33-44-55")
    monkeypatch.setattr("trae2api.login.Hardware.read", lambda: value)
    return value


def replies(request):
    if request.url.path.endswith("device_register/"):
        return httpx.Response(200, json={"device_id_str": "1234567890123456789", "install_id_str": "9876543210123456789"},
                              headers={"x-tt-store-region": "cn"})
    if request.url.path.endswith("app_alert_check/"):
        return httpx.Response(200, json={"message": "success", "data": {"is_activated": 1}})
    if request.url.path.endswith("ExchangeToken"):
        return httpx.Response(200, json={"Result": {"Token": "synthetic-token", "RefreshToken": "synthetic-refresh", "TokenExpireDuration": 60000}})
    if request.url.path.endswith("GetUserInfo"):
        return httpx.Response(200, json={"Result": {"UserID": "synthetic-user", "AIRegion": "CN"}})
    raise AssertionError("unexpected endpoint")


def test_identity_and_keys_persist_while_pkce_is_fresh(tmp_path):
    path = tmp_path / "account.json"
    with httpx.Client(transport=httpx.MockTransport(replies)) as client:
        first = TraeLoginFlow(creds_file=path, http=client)
        second = TraeLoginFlow(creds_file=path, http=client)
        assert first.machine_id == second.machine_id
        assert first.private_key_pem == second.private_key_pem
        assert first.code_verifier != second.code_verifier
        assert first.device_id == second.device_id == ""
    assert not path.exists()
    assert IdentityStore(path).path.exists()


def test_registration_body_uses_real_hardware_gzip_and_native_numeric_fields(hardware):
    params, compressed = registration_request(hardware, "3.4.20", now=1700000000.125)
    body = json.loads(gzip.decompress(compressed))
    assert params["pc_uuid"] == hardware.pc_uuid
    assert params["os_version"] == "10.0.19045"
    assert params["os"] == "Windows" and params["device_platform"] == "PC"
    assert body["magic_tag"] == "ss_app_log"
    assert body["_gen_time"] == 1700000000125
    assert body["header"]["device_id"] == body["header"]["install_id"] == 0
    assert body["header"]["aid"] == 787976
    assert body["header"]["device_model"] == hardware.model
    assert body["header"]["mc"] == hardware.mac


def test_registration_and_activation_are_reused_without_new_identity(tmp_path, hardware):
    path = tmp_path / "account.json"
    seen = []
    def handler(request):
        seen.append(request)
        return replies(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = TraeLoginFlow(creds_file=path, http=client)
        first.prepare_device()
        second = TraeLoginFlow(creds_file=path, http=client)
        second.prepare_device()
    assert [r.url.path for r in seen] == ["/service/2/desktop/device_register/", "/service/2/app_alert_check/"]
    assert first.device_id == second.device_id == "1234567890123456789"
    assert first.private_key_pem == second.private_key_pem
    assert second._device_info()["DeviceBrand"] == "Actual Manufacturer"
    assert second._device_info()["DeviceCPU"] == "AMD Ryzen Synthetic"
    assert second._device_info()["OSInfo"] == "windows"
    assert "python" not in seen[0].headers["user-agent"].lower()
    assert seen[0].headers["content-encoding"] == "gzip"


def test_activation_failure_keeps_registration_and_resumes_only_activation(tmp_path, hardware):
    path = tmp_path / "account.json"
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("app_alert_check/") and seen.count(request.url.path) == 1:
            return httpx.Response(200, json={"message": "failed"})
        return replies(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = TraeLoginFlow(creds_file=path, http=client)
        with pytest.raises(ValueError, match="not confirmed"):
            first.prepare_device()
        registered_key = IdentityStore(path).load().private_key_pem
        second = TraeLoginFlow(creds_file=path, http=client)
        second.prepare_device()
        assert second.private_key_pem == registered_key
    assert seen.count("/service/2/desktop/device_register/") == 1
    assert seen.count("/service/2/app_alert_check/") == 2


@pytest.mark.parametrize("body", [{}, {"device_id_str": "0", "install_id_str": "123"},
    {"device_id_str": 123, "install_id_str": "456"}, {"device_id_str": "uuid", "install_id_str": "456"}])
def test_invalid_registration_does_not_mark_profile_registered(tmp_path, hardware, body):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
        flow = TraeLoginFlow(creds_file=tmp_path / "account.json", http=client)
        with pytest.raises(ValueError, match="device_id_str"):
            flow.prepare_device()
    assert not flow.identity_store.load().registered


def test_corrupt_profile_is_not_silently_regenerated(tmp_path):
    store = IdentityStore(tmp_path / "account.json")
    store.path.write_text('{"version":1,"privateKeyPEM":"broken"}')
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="refusing to replace"):
        store.load()
    assert store.path.read_bytes() == before


def simulate_callback(flow):
    flow.result["AuthCode"] = "synthetic-code"
    flow._done.set()
    return 12345


def test_login_success_uses_matching_identity_and_saves_selected_credentials(tmp_path, hardware, monkeypatch):
    path = tmp_path / "selected.json"
    path.write_text('{"old":"credentials"}')
    seen = []
    def handler(request):
        seen.append(request)
        return replies(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        flow = TraeLoginFlow(creds_file=path, http=client)
        monkeypatch.setattr(flow, "_start_server", lambda: simulate_callback(flow))
        auth = flow.start(open_browser=False, log=lambda text: None)
        auth.http.close()
    data = json.loads(path.read_text())
    assert data["device"]["deviceId"] == flow.device_id
    assert data["device"]["privateKeyPEM"] == flow.private_key_pem
    assert data["device"]["deviceBrand"] == hardware.brand
    exchange = next(r for r in seen if r.url.path.endswith("ExchangeToken"))
    body = json.loads(exchange.content)
    assert body["DeviceInfo"]["DeviceID"] == data["device"]["deviceId"]
    assert body["DeviceInfo"]["DevicePublicKey"] == flow.public_key_pem
    assert "DeviceProof" not in body
    with httpx.Client(transport=httpx.MockTransport(replies)) as client:
        restored = TraeAuth(creds_file=path, http=client)
        restored.load()
        assert restored.device.device_public_key == flow.public_key_pem


def test_cli_forwards_selected_credentials_and_prepare_mode(tmp_path, monkeypatch):
    from trae2api.__main__ import main
    calls = []
    monkeypatch.setattr(sys, "argv", ["trae2api", "login", "--creds", str(tmp_path / "separate.json"), "--prepare-device"])
    monkeypatch.setattr("trae2api.login.run_login", lambda **kwargs: calls.append(kwargs))
    main()
    assert calls[0]["creds_file"] == str(tmp_path / "separate.json")
    assert calls[0]["prepare_only"] is True


def test_failed_profile_fetch_preserves_previous_credentials(tmp_path, hardware, monkeypatch):
    path = tmp_path / "account.json"
    previous = b'{"old":"credentials"}'
    path.write_bytes(previous)
    def handler(request):
        if request.url.path.endswith("GetUserInfo"):
            return httpx.Response(503)
        return replies(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        flow = TraeLoginFlow(creds_file=path, http=client)
        monkeypatch.setattr(flow, "_start_server", lambda: simulate_callback(flow))
        with pytest.raises(ValueError, match="HTTP 503"):
            flow.start(open_browser=False, log=lambda text: None)
    assert path.read_bytes() == previous


def test_confirmation_does_not_finish_login_without_authcode(tmp_path, hardware):
    with httpx.Client(transport=httpx.MockTransport(replies)) as upstream:
        flow = TraeLoginFlow(creds_file=tmp_path / "account.json", http=upstream)
        port = flow._start_server()
        try:
            with httpx.Client(trust_env=False) as browser:
                browser.get(f"http://127.0.0.1:{port}/login-success")
                assert not flow._done.is_set()
                response = browser.get(f"http://127.0.0.1:{port}/authorize", params={"authCodeInfo": "[]"})
                assert response.status_code == 400 and not flow._done.is_set()
                browser.get(f"http://127.0.0.1:{port}/authorize", params={"authCodeInfo": '{"AuthCode":"code"}'})
                assert flow._done.is_set()
        finally:
            flow._server.shutdown()
            flow._server.server_close()


def test_expiry_duration_is_relative_to_now(monkeypatch):
    monkeypatch.setattr("trae2api.login.time.time", lambda: 1700000000)
    assert _iso_from_ms_or_iso(None, 60000) == "2023-11-14T22:14:20Z"


def test_smbios_uuid_byte_order_and_invalid_uuid():
    table = bytearray(27)
    table[0:2] = bytes([1,25])
    table[8:24] = bytes.fromhex("00112233445566778899aabbccddeeff")
    data = b"\x00\x03\x02\x00" + struct.pack("<I", len(table)) + table
    assert uuid_from_smbios(data) == "33221100-5544-7766-8899-AABBCCDDEEFF"
    table[8:24] = b"\0" * 16
    with pytest.raises(ValueError, match="UUID"):
        uuid_from_smbios(data[:8] + table)
