"""Reviewed native cache/getter contracts, with synthetic records and HTTP."""
import asyncio
from dataclasses import replace

import httpx
import pytest

from trae2api.aha_device_cache import DeviceRecord
from trae2api.aha_device_service import AhaDeviceService
from trae2api.device_hardware import Hardware
from trae2api.login_identity import IdentityStore

UUID = "33221100-5544-7766-8899-AABBCCDDEEFF"


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("live HTTP forbidden")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)


@pytest.fixture
def hardware():
    return Hardware(UUID, "test-disk", "Test Model", "Test Brand", "Test CPU",
                    "windows", "Windows Test", "10.0.19045", "00-11-22-33-44-55")


def service(tmp_path, hardware, http=None):
    return AhaDeviceService(IdentityStore(tmp_path / "account.json"), http=http,
                            hardware_reader=lambda: hardware)


def response(request):
    assert request.url.path.endswith("device_register/")
    return httpx.Response(200, json={"device_id_str": "12345", "install_id_str": "67890"})


def test_record_roundtrip_and_install_id_is_not_numeric_validation():
    # Native cache validation does not impose the login adapter's IID policy.
    payload = DeviceRecord("12345", "", UUID).as_dict()
    record = DeviceRecord.load(payload, UUID)
    assert record.device_id == "12345" and record.install_id == ""
    assert set(payload) == {"version", "uuid", "device_id_str", "install_id_str"}
    assert payload["version"] == "1.2"


@pytest.mark.parametrize("patch", [
    {"version": 1.2}, {"version": "1.3"}, {"uuid": UUID.lower()}, {"uuid": None},
    {"device_id_str": "0"}, {"device_id_str": "000"}, {"device_id_str": "uuid"},
    {"device_id_str": 12345}, {"install_id_str": None},
])
def test_bad_record_is_a_miss(patch):
    payload = DeviceRecord("12345", "67890", UUID).as_dict()
    payload.update(patch)
    assert DeviceRecord.load(payload, UUID) is None


def test_legacy_cache_migration_keeps_installation_and_remote_ids(tmp_path, hardware):
    svc = service(tmp_path, hardware)
    with svc.store.locked():
        identity = svc.store.load()
        identity.device_id, identity.install_id = "12345", "67890"
        identity.hardware_uuid, identity.registered = UUID, True
        svc.store.save(identity)
    result = svc.get_device_id()
    stored = svc.store.load()
    assert result.device_id == "12345"
    assert isinstance(stored.device_cache, str)
    assert DeviceRecord.load(stored.device_cache, UUID).as_dict() == DeviceRecord("12345", "67890", UUID).as_dict()
    assert stored.private_key_pem == identity.private_key_pem
    assert stored.machine_id == identity.machine_id


@pytest.mark.parametrize("bad_record", [{}, "broken record", {"version": "1.3"}, None])
def test_bad_device_cache_does_not_destroy_key_or_reuse_legacy_flags(tmp_path, hardware, bad_record):
    import json
    svc = service(tmp_path, hardware)
    svc.get_device_id()
    identity = svc.store.load()
    identity.device_id, identity.install_id = "12345", "67890"
    identity.hardware_uuid, identity.registered = UUID, True
    identity.device_cache = bad_record
    data = identity.as_dict()
    data["ahaDeviceCache"] = bad_record  # explicit null is invalid, not a legacy record.
    svc.store.path.write_text(json.dumps(data), encoding="utf-8")
    before = svc.store.path.read_bytes()
    result = service(tmp_path, hardware).get_device_id()
    assert result.device_id == "0" and result.source == "local"
    assert result.identity.private_key_pem == identity.private_key_pem
    assert svc.store.path.read_bytes() == before


def test_uuid_mismatch_then_registration_uses_current_hardware(tmp_path, hardware):
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        original = service(tmp_path, hardware, http).get_device_id(allow_network=True)
    changed = replace(hardware, pc_uuid="44332211-6655-8877-8899-AABBCCDDEEFF")
    def handler(request):
        assert request.url.params["pc_uuid"] == changed.pc_uuid
        return response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        svc = service(tmp_path, changed, http)
        assert svc.get_device_id().device_id == "0"
        result = svc.get_device_id(allow_network=True)
    assert result.identity.hardware_uuid == changed.pc_uuid
    assert DeviceRecord.load(result.identity.device_cache, changed.pc_uuid).uuid == changed.pc_uuid
    # Fixed mock response intentionally returns the same DID; preserve its key.
    assert result.identity.private_key_pem == original.identity.private_key_pem


def test_async_getters_wait_and_share_one_explicit_registration(tmp_path, hardware):
    requests = []
    def handler(request):
        requests.append(request)
        return response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        svc = service(tmp_path, hardware, http)
        async def run():
            first = asyncio.create_task(svc.get_device_id_async())
            second = asyncio.create_task(svc.get_device_id_async())
            await asyncio.sleep(0)
            assert not first.done() and not second.done() and not requests
            await svc.register_device_async()
            a, b = await asyncio.gather(first, second)
            assert a.device_id == b.device_id == "12345"
        asyncio.run(run())
    assert len(requests) == 1


def test_timeout_uses_local_main_then_late_remote_updates_both_ids(tmp_path, hardware):
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        svc = service(tmp_path, hardware, http)
        async def run():
            result = await svc.resolve_device_id_async(timeout=0)
            assert result.source == "timeout" and not result.identity.registered
            assert result.device_id == UUID and result.remote_device_id == "0"
            assert svc.get_all_ids() == {"deviceId": UUID, "localDeviceId": UUID, "remoteDeviceId": "0"}
            await svc.register_device_async()
            assert (await svc.get_device_id_async()).device_id == "12345"
            assert svc.get_all_ids() == {"deviceId": "12345", "localDeviceId": UUID, "remoteDeviceId": "12345"}
        asyncio.run(run())


def test_cancelled_getter_does_not_cancel_other_getters_or_registration(tmp_path, hardware):
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        svc = service(tmp_path, hardware, http)
        async def run():
            first = asyncio.create_task(svc.get_device_id_async())
            second = asyncio.create_task(svc.get_device_id_async())
            await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            await svc.register_device_async()
            assert (await second).device_id == "12345"
        asyncio.run(run())


def test_resolved_getter_returns_memory_without_rereading_profile(tmp_path, hardware, monkeypatch):
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        svc = service(tmp_path, hardware, http)
        svc.get_device_id(allow_network=True)
    def forbidden():
        raise AssertionError("native-style getter must reuse resolved memory state")
    monkeypatch.setattr(svc.store, "load", forbidden)
    assert svc.get_device_id().device_id == "12345"
    assert asyncio.run(svc.get_device_id_async()).device_id == "12345"


def test_returned_identity_mutation_does_not_modify_internal_ids(tmp_path, hardware):
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        svc = service(tmp_path, hardware, http)
        first = svc.get_device_id(allow_network=True)
    identity = svc.store.load()
    identity.device_cache = DeviceRecord("12345", "67890", UUID).as_dict()
    svc.store.save(identity)
    svc = service(tmp_path, hardware)
    first = svc.get_device_id()
    first.identity.device_id = "99999"
    first.identity.device_cache["device_id_str"] = "99999"
    second = svc.get_device_id()
    assert second.device_id == "12345"
    second.identity.device_id = "88888"
    second.identity.device_cache["device_id_str"] = "88888"
    third = asyncio.run(svc.get_device_id_async())
    assert third.device_id == "12345"
    third.identity.device_id = "77777"
    assert svc.get_all_ids()["deviceId"] == "12345"
    assert svc.store.load().device_id == "12345"


def test_async_cached_getter_is_immediate_and_hardware_is_sampled_once(tmp_path, hardware):
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        service(tmp_path, hardware, http).get_device_id(allow_network=True)
    seen = []
    def reader():
        seen.append(1)
        return hardware
    svc = AhaDeviceService(IdentityStore(tmp_path / "account.json"), hardware_reader=reader)
    async def run():
        assert (await svc.resolve_device_id_async(timeout=0)).device_id == "12345"
        assert (await svc.get_device_id_async()).device_id == "12345"
        assert svc.get_device_id().device_id == "12345"
    asyncio.run(run())
    assert len(seen) == 1


def test_registered_id_reaches_waiters_even_if_activation_fails(tmp_path, hardware):
    def handler(request):
        if request.url.path.endswith("device_register/"):
            return response(request)
        return httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        svc = service(tmp_path, hardware, http)
        async def run():
            waiter = asyncio.create_task(svc.get_device_id_async())
            await asyncio.sleep(0)
            with pytest.raises(ValueError, match="HTTP 503"):
                await svc.register_device_async(require_activation=True)
            result = await waiter
            assert result.device_id == "12345" and not result.identity.activated
        asyncio.run(run())
    assert svc.store.load().registered and not svc.store.load().activated


def test_concurrent_registration_callers_reuse_one_remote_registration(tmp_path, hardware):
    seen = []
    def handler(request):
        seen.append(request)
        return response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        svc = service(tmp_path, hardware, http)
        async def run():
            results = await asyncio.gather(*(svc.register_device_async() for _ in range(3)))
            assert all(result.device_id == "12345" for result in results)
        asyncio.run(run())
    assert len(seen) == 1


def test_cancelling_registration_wait_does_not_discard_late_result(tmp_path, hardware):
    import threading
    started, release = threading.Event(), threading.Event()
    def handler(request):
        started.set()
        assert release.wait(5), "test did not release mock registration"
        return response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        svc = service(tmp_path, hardware, http)
        async def run():
            registration = asyncio.create_task(svc.register_device_async())
            try:
                assert await asyncio.to_thread(started.wait, 5)
                registration.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await registration
                waiter = asyncio.create_task(svc.get_device_id_async())
                await asyncio.sleep(0)
                release.set()
                assert (await waiter).device_id == "12345"
            finally:
                release.set()
        asyncio.run(run())
    assert svc.get_all_ids()["remoteDeviceId"] == "12345"


def test_timeout_remains_independent_of_inflight_registration(tmp_path, hardware):
    import threading
    started, release = threading.Event(), threading.Event()
    def handler(request):
        started.set()
        assert release.wait(5)
        return response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        svc = service(tmp_path, hardware, http)
        async def run():
            registration = asyncio.create_task(svc.register_device_async())
            try:
                assert await asyncio.to_thread(started.wait, 5)
                result = await svc.resolve_device_id_async(timeout=0)
                assert result.device_id == UUID and result.remote_device_id == "0"
                assert not registration.done()
                release.set()
                await registration
                assert svc.get_all_ids()["deviceId"] == "12345"
            finally:
                release.set()
        asyncio.run(run())
