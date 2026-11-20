"""Synthetic hardware + in-memory HTTP only; no native cache or live server."""
import json

import httpx
import pytest

from trae2api.aha_device_service import AhaDeviceService
from trae2api.aha_device_cache import DeviceRecord
from trae2api.device_hardware import Hardware
from trae2api.login_identity import IdentityStore


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("live HTTP forbidden in device service tests")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)


@pytest.fixture
def hardware():
    return Hardware("33221100-5544-7766-8899-AABBCCDDEEFF", "test-disk", "Test Model", "Test Brand",
                    "Test CPU", "windows", "Windows Test", "10.0.19045", "00-11-22-33-44-55")


def service(tmp_path, hardware, client=None):
    return AhaDeviceService(IdentityStore(tmp_path / "account.json"), http=client,
                            hardware_reader=lambda: hardware)


def registration_reply():
    return httpx.Response(200, json={"device_id_str": "123456789", "install_id_str": "987654321"})


def cached(svc, hardware, *, activated=False):
    identity = svc.get_device_id().identity
    identity.device_id, identity.install_id = "123456789", "987654321"
    identity.hardware_uuid = hardware.pc_uuid
    identity.registered, identity.activated = True, activated
    identity.device_cache = DeviceRecord(identity.device_id, identity.install_id, hardware.pc_uuid).as_dict()
    svc.store.save(identity)
    return identity


def test_offline_fallback_is_separate_and_installation_persists(tmp_path, hardware):
    first = service(tmp_path, hardware).get_device_id()
    second = service(tmp_path, hardware).get_device_id()
    assert first.source == second.source == "local"
    assert first.device_id == first.install_id == "0"
    assert first.guaranteed_device_id == first.local_device_id == hardware.pc_uuid
    assert not first.identity.registered and not first.identity.activated
    assert first.identity.private_key_pem == second.identity.private_key_pem
    assert first.identity.machine_id == second.identity.machine_id
    assert not (tmp_path / "account.json").exists()
    assert hardware.pc_uuid not in repr(first)
    assert "PRIVATE KEY" not in repr(first)


def test_legacy_unverified_id_is_not_returned_as_remote_id(tmp_path, hardware):
    (tmp_path / "account.json").write_text(json.dumps({"device": {"deviceId": "old-random-uuid"}}))
    result = service(tmp_path, hardware).get_device_id()
    assert result.identity.device_id == "old-random-uuid"
    assert result.device_id == "0"
    assert result.guaranteed_device_id == hardware.pc_uuid


def test_configuring_http_does_not_enable_network(tmp_path, hardware):
    def forbidden(request):
        raise AssertionError("default call must not use even the mock transport")
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        assert service(tmp_path, hardware, client).get_device_id().source == "local"


def test_network_requires_explicit_client(tmp_path, hardware):
    with pytest.raises(ValueError, match="explicitly supplied HTTP client"):
        service(tmp_path, hardware).get_device_id(allow_network=True)


def test_cached_remote_id_is_available_before_activation_without_http(tmp_path, hardware):
    svc = service(tmp_path, hardware)
    cached(svc, hardware)
    result = svc.get_device_id()
    assert result.source == "cache"
    assert result.device_id == result.guaranteed_device_id == "123456789"
    assert result.install_id == "987654321"
    assert not result.identity.activated
    with pytest.raises(ValueError, match="network access is disabled"):
        svc.get_device_id(require_activation=True)


def test_registration_saves_before_activation_and_uses_server_ids(tmp_path, hardware):
    seen = []
    def handler(request):
        seen.append(request.url.path)
        assert request.url.params["pc_uuid"] == hardware.pc_uuid
        if request.url.path.endswith("device_register/"):
            return registration_reply()
        assert svc.store.load().registered
        assert not svc.store.load().activated
        return httpx.Response(200, json={"message": "success", "data": {"is_activated": True}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        svc = service(tmp_path, hardware, client)
        result = svc.get_device_id(allow_network=True, require_activation=True)
        restored = svc.get_device_id(allow_network=True, require_activation=True)
    assert seen == ["/service/2/desktop/device_register/", "/service/2/app_alert_check/"]
    assert result.source == "registration" and restored.source == "cache"
    assert result.device_id == "123456789" and restored.identity.activated
    assert result.identity.private_key_pem == restored.identity.private_key_pem


def test_registration_can_be_resolved_without_activation(tmp_path, hardware):
    seen = []
    def handler(request):
        seen.append(request.url.path)
        assert request.url.path.endswith("device_register/")
        return registration_reply()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        svc = service(tmp_path, hardware, client)
        result = svc.get_device_id(allow_network=True)
    assert len(seen) == 1
    assert result.identity.registered and not result.identity.activated
    assert service(tmp_path, hardware).get_device_id().device_id == result.device_id


def test_activation_failure_resumes_without_reregistration_or_key_change(tmp_path, hardware):
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("device_register/"):
            return registration_reply()
        if seen.count(request.url.path) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"message": "success", "data": {"is_activated": 1}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        svc = service(tmp_path, hardware, client)
        with pytest.raises(ValueError, match="HTTP 503"):
            svc.get_device_id(allow_network=True, require_activation=True)
        before = svc.store.load()
        assert before.registered and not before.activated
        after = service(tmp_path, hardware, client).get_device_id(allow_network=True, require_activation=True)
    assert seen.count("/service/2/desktop/device_register/") == 1
    assert seen.count("/service/2/app_alert_check/") == 2
    assert before.private_key_pem == after.identity.private_key_pem


@pytest.mark.parametrize("failure", ["network", "invalid_response"])
def test_failed_registration_does_not_promote_fallback_or_lose_installation(tmp_path, hardware, failure):
    def handler(request):
        if failure == "network":
            raise httpx.ConnectError("synthetic error", request=request)
        return httpx.Response(200, json={"device_id_str": 123, "install_id_str": "123"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        svc = service(tmp_path, hardware, client)
        before = svc.get_device_id()
        with pytest.raises(ValueError):
            svc.get_device_id(allow_network=True)
        after = svc.get_device_id()
    assert after.device_id == "0" and not after.identity.registered
    assert after.identity.private_key_pem == before.identity.private_key_pem


def test_hardware_mismatch_is_a_cache_miss_and_preserves_installation(tmp_path, hardware):
    svc = service(tmp_path, hardware)
    identity = cached(svc, hardware)
    identity.hardware_uuid = "DIFFERENT-HARDWARE"
    identity.device_cache["uuid"] = "DIFFERENT-HARDWARE"
    svc.store.save(identity)
    before = svc.store.path.read_bytes()
    result = svc.get_device_id()
    assert result.device_id == "0" and result.source == "local"
    assert result.identity.private_key_pem == identity.private_key_pem
    assert svc.store.path.read_bytes() == before


def test_corrupt_cache_is_not_replaced_with_new_identity(tmp_path, hardware):
    svc = service(tmp_path, hardware)
    svc.store.path.write_text('{"version":1}')
    before = svc.store.path.read_bytes()
    with pytest.raises(ValueError, match="refusing to replace"):
        svc.get_device_id(allow_network=True)
    assert svc.store.path.read_bytes() == before


def test_existing_profile_lock_blocks_parallel_resolution(tmp_path, hardware):
    svc = service(tmp_path, hardware)
    with svc.store.locked():
        with pytest.raises(ValueError, match="another login"):
            svc.get_device_id()


def test_missing_hardware_uuid_fails_without_creating_profile(tmp_path, hardware):
    from dataclasses import replace
    svc = service(tmp_path, replace(hardware, pc_uuid=""))
    with pytest.raises(ValueError, match="hardware UUID unavailable"):
        svc.get_device_id()
    assert not svc.store.path.exists()
