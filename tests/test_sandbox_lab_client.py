import json

import httpx
import pytest

from trae2api.sandbox_lab import storage
from trae2api.sandbox_lab.client import LabClient, LabFailure
from trae2api.sandbox_lab.config import local_config
from trae2api.sandbox_lab.fixtures import DeviceFixture, attributes_for
from trae2api.sandbox_lab.mock_server import CAPABILITIES, MockServer, MockState, running_mock


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "OUTPUT_ROOT", tmp_path / "lab")
    return local_config(8765, str(tmp_path / "lab" / "client"))


def test_handshake_required_before_posts(cfg):
    seen = []
    client = LabClient(cfg, transport=httpx.MockTransport(lambda r: seen.append(r)))
    try:
        with pytest.raises(LabFailure, match="capability_required"):
            client.register("lab-experiment-a", DeviceFixture("fixture-a", attributes_for("fixture-a")))
        assert seen == []
        assert client.requests_sent == 0
    finally:
        client.close()


@pytest.mark.parametrize("override", [
    {"rewards_enabled": True}, {"rewards_enabled": 0}, {"environment": "production"},
    {"protocol_version": True}, {"supported_fixture_schema": "1"}, {"service": "other-service"},
])
def test_bad_handshake_rejected(cfg, override):
    body = {**CAPABILITIES, **override}
    client = LabClient(cfg, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    try:
        with pytest.raises(LabFailure, match="capability_mismatch"):
            client.capabilities()
        assert not client.ready
        assert client.requests_sent == 1
    finally:
        client.close()


@pytest.mark.parametrize("body,label", [
    ({"accepted": False}, "business_rejected"),
    ({"accepted": "true"}, "invalid_accepted_type"),
    ({"accepted": 1}, "invalid_accepted_type"),
    ({"accepted": True}, "invalid_sandbox_ids"),
    ({"accepted": True, "sandbox_device_id": "production-id", "sandbox_install_id": "lab-i"}, "invalid_sandbox_ids"),
    ({"accepted": True, "sandbox_device_id": "lab-", "sandbox_install_id": "lab-i"}, "invalid_sandbox_ids"),
])
def test_register_strict_response_types(cfg, body, label):
    seen = []
    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=CAPABILITIES if len(seen) == 1 else body)
    client = LabClient(cfg, transport=httpx.MockTransport(handler))
    try:
        client.capabilities()
        with pytest.raises(LabFailure, match=label):
            client.register("lab-experiment-a", DeviceFixture("fixture-a", attributes_for("fixture-a")))
        assert len(seen) == 2
    finally:
        client.close()


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_activation_strict_bool(cfg, value):
    def handler(request):
        if request.url.path.endswith("capabilities"):
            return httpx.Response(200, json=CAPABILITIES)
        if request.url.path.endswith("register"):
            return httpx.Response(200, json={"accepted": True, "sandbox_device_id": "lab-d", "sandbox_install_id": "lab-i"})
        return httpx.Response(200, json={"accepted": True, "activated": value})
    client = LabClient(cfg, transport=httpx.MockTransport(handler))
    try:
        client.capabilities()
        reg = client.register("lab-experiment-a", DeviceFixture("fixture-a", attributes_for("fixture-a")))
        with pytest.raises(LabFailure, match="activation_not_confirmed"):
            client.activate("lab-experiment-a", reg)
        before = client.requests_sent
        with pytest.raises(LabFailure, match="registration_not_in_this_experiment"):
            client.activate("lab-experiment-b", reg)
        assert client.requests_sent == before
    finally:
        client.close()


@pytest.mark.parametrize("response,label", [
    (httpx.Response(302, headers={"Location": "https://api.trae.cn"}), "redirect_rejected"),
    (httpx.Response(200, text="not json"), "invalid_json"),
    (httpx.Response(200, json=[]), "response_not_object"),
    (httpx.Response(200, content=b"x" * (65536 + 1)), "response_too_large"),
])
def test_malformed_or_redirect_no_followup(cfg, response, label):
    seen = []
    def handler(request):
        seen.append(request)
        return response
    client = LabClient(cfg, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(LabFailure, match=label):
            client.capabilities()
        assert len(seen) == client.requests_sent == 1
    finally:
        client.close()


def test_mock_state_idempotence_and_experiment_isolation():
    state = MockState()
    body = {"experiment_id": "lab-experiment-a", "app_id": "local-device-lab",
            "fixture_id": "fixture-a", "attributes": attributes_for("fixture-a")}
    code, first = state.register(body)
    assert code == 200
    assert state.register(body) == (200, first)
    _, renamed = state.register({**body, "fixture_id": "fixture-a-display", "attributes": attributes_for("fixture-a-display")})
    assert first["sandbox_device_id"] != renamed["sandbox_device_id"]
    assert first["sandbox_physical_id"] == renamed["sandbox_physical_id"]
    _, other = state.register({**body, "experiment_id": "lab-experiment-b"})
    assert other["sandbox_device_id"] != first["sandbox_device_id"]
    activation = {"experiment_id": "lab-experiment-a", "app_id": "local-device-lab",
                  "sandbox_device_id": first["sandbox_device_id"], "sandbox_install_id": first["sandbox_install_id"]}
    assert state.activate(activation) == (200, {"accepted": True, "activated": True})
    assert state.activate({**activation, "experiment_id": "lab-experiment-b"})[0] == 400
    assert MockState().activate(activation)[0] == 400
    assert state.register({**body, "attributes": attributes_for("fixture-invalid")})[0] == 400
    assert state.register({**body, "token": "must-not-be-accepted"})[0] == 400
    assert state.activate({**activation, "sandbox_install_id": "lab-other-install"})[0] == 400


def test_real_http_mock_rejects_unknown_operations_and_invalid_bodies():
    with running_mock() as mock, httpx.Client(trust_env=False, timeout=3) as http:
        base = f"http://127.0.0.1:{mock.server_port}"
        assert http.get(base + "/lab/capabilities").json() == CAPABILITIES
        for path in ("/lab/authorize", "/lab/claim", "/trae/api/v3/oauth/ExchangeToken"):
            assert http.post(base + path, json={}).status_code == 404
        for body in ([], {}, {"synthetic": False}):
            assert http.post(base + "/lab/register", json=body).status_code == 400
        assert http.post(base + "/lab/register", content=b"x" * 17000,
                         headers={"Content-Type": "application/json"}).status_code == 400


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "10.0.0.1", "::1"])
def test_mock_never_binds_nonfixed_loopback(host):
    with pytest.raises(ValueError):
        MockServer(host=host)
