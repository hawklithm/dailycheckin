import json
from urllib.parse import parse_qs, urlparse

import httpx

from trae2api import client_metadata
from trae2api.auth import TraeAuth
from trae2api.login import TraeLoginFlow


def test_reads_product_app_version_not_editor_version(tmp_path, monkeypatch):
    path = tmp_path / "product.json"
    path.write_text(json.dumps({"appVersion": "3.4.20", "version": "1.107.1"}))
    monkeypatch.setenv("TRAE2API_PRODUCT_JSON", str(path))
    assert client_metadata.client_version() == "3.4.20"


def test_version_falls_back_to_saved_value_without_install(monkeypatch):
    monkeypatch.setattr(client_metadata, "installed_version", lambda: "")
    assert client_metadata.client_version("3.4.9") == "3.4.9"


def test_device_version_survives_save_and_load(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        auth = TraeAuth(creds_file=tmp_path / "creds.json", http=client)
        auth.device.client_version = "3.4.99"
        auth.device.device_id = "original-device"
        auth.save()
        restored = TraeAuth(creds_file=auth.creds_file, http=client)
        restored.load()
    assert restored.device.client_version == "3.4.99"
    assert restored.device.device_id == "original-device"


def test_login_uses_one_version_and_system_model(monkeypatch):
    monkeypatch.setattr("trae2api.login.client_version", lambda: "3.4.20")
    monkeypatch.setattr("trae2api.login.device_model", lambda: "System Model")
    flow = TraeLoginFlow(device_name="User Label")
    device = flow._device_info()
    assert device["ClientVersion"] == "3.4.20"
    assert device["DeviceModel"] == device["DeviceBrand"] == "System Model"
    assert device["DeviceName"] == "User Label"
    query = parse_qs(urlparse(flow.build_login_url(12345)).query)
    assert query["x_app_version"] == ["3.4.20"]
    assert query["x_device_brand"] == ["System Model"]
    calls = []
    def post(url, body, token=""):
        calls.append(body)
        return {"Result": {"Token": "test-token"}}
    monkeypatch.setattr(flow, "_post_json", post)
    flow.exchange_auth_code("test-code")
    flow.fetch_user_info("test-token")
    assert all(body["IDEVersion"] == "3.4.20" for body in calls)
