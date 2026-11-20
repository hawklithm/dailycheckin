"""Native lifecycle branches with finite scripted backends; no live service."""
import asyncio
from contextlib import asynccontextmanager
import gzip
import json

import httpx
import pytest

from trae2api.aha_device_cache import DeviceRecord
from trae2api.aha_device_service import AhaDeviceService
from trae2api.aha_native_lifecycle import NativeAhaDeviceService, RegisterReply, ActiveReply
from trae2api.device_hardware import Hardware
from trae2api.login_identity import IdentityStore

UUID = "33221100-5544-7766-8899-AABBCCDDEEFF"


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("real network forbidden")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)


class Backend:
    def __init__(self, replies=None, active=None):
        self.replies = list(replies or [RegisterReply("12345", "67890")])
        self.active = list(active or [ActiveReply()])
        self.calls = []

    async def register(self, device_id, install_id):
        self.calls.append(("register", device_id, install_id))
        assert self.replies, "unexpected extra registration"
        return self.replies.pop(0)

    async def activate(self, device_id, install_id):
        self.calls.append(("activate", device_id, install_id))
        assert self.active, "unexpected extra activation"
        return self.active.pop(0)


@asynccontextmanager
async def native(**kwargs):
    service = NativeAhaDeviceService(hardware_uuid=UUID, **kwargs)
    try:
        yield service
    finally:
        await service.close()


def test_offline_start_does_not_register_and_local_timeout_does_not_promote_remote():
    async def run():
        backend = Backend()
        async with native(backend=backend) as service:
            await service.start()
            result = await service.resolve(timeout=0)
            assert result == {"deviceId": UUID, "localDeviceId": UUID, "remoteDeviceId": "0"}
            assert not backend.calls
    asyncio.run(run())


def test_missing_device_info_object_has_local_uuid_only():
    import uuid
    async def run():
        service = NativeAhaDeviceService(hardware_uuid=None)
        try:
            assert uuid.UUID(service.local_device_id).version == 4
            result = await service.resolve(timeout=0)
            assert result["remoteDeviceId"] == "0" and service.device_id == ""
        finally:
            await service.close()
    asyncio.run(run())


@pytest.mark.parametrize("region,ready,register", [("CN",False,False), ("cn",False,False),
                                                   ("SG",True,False), ("SG",False,True)])
def test_startup_refresh_decision_uses_region_record(region, ready, register):
    async def run():
        backend = Backend()
        async with native(record=DeviceRecord("11", "22", UUID), backend=backend,
                          app_region=region, region_record_ready=ready) as service:
            await service.start(allow_network=True)
            await service.wait_worker()
            assert bool(backend.calls) == register
            if register:
                assert backend.calls[0] == ("register", "11", "22")
            else:
                assert await service.get_device_id() == "11"
    asyncio.run(run())


def test_old_id_setter_with_empty_memory_does_not_fill_remote_id():
    async def run():
        saved = []
        async def save(record): saved.append(record)
        async with native(save_cache=save) as service:
            assert await service.set_old_device_id("12345")
            assert service.device_id == "" and service.old_device_id == "12345"
            assert not saved
    asyncio.run(run())


def test_old_id_setter_replaces_nonempty_memory_and_saves_record():
    async def run():
        saved = []
        async def save(record): saved.append(record)
        async with native(record=DeviceRecord("11", "22", UUID), save_cache=save) as service:
            assert await service.get_device_id("33") == "33"
            assert saved == [DeviceRecord("33", "22", UUID)]
            assert not await service.set_old_device_id("0")
            assert service.device_id == "33"
    asyncio.run(run())


@pytest.mark.parametrize("flags2,flags3", [(False,False), (False,True), (True,False), (True,True)])
def test_pending_callback_delivery_before_or_after_activation(flags2, flags3):
    async def run():
        activation_started, release = asyncio.Event(), asyncio.Event()
        order = []
        class Gated(Backend):
            async def activate(self, device_id, install_id):
                order.append("activate")
                activation_started.set()
                await release.wait()
                return await super().activate(device_id, install_id)
        async def save(record): order.append("save")
        async with native(backend=Gated(), save_cache=save, flags_2=flags2, flags_3=flags3) as service:
            pending = asyncio.create_task(service.get_device_id())
            await asyncio.sleep(0)
            await service.start(allow_network=True)
            await activation_started.wait()
            await asyncio.sleep(0)
            assert pending.done() == (not (flags2 and flags3))
            assert order == ["save", "activate"]
            # A NEW getter sees the nonempty memory ID even in deferred mode.
            assert await service.get_device_id() == "12345"
            release.set()
            await service.wait_worker()
            assert await pending == "12345"
    asyncio.run(run())


def test_failed_registration_copies_zero_but_does_not_notify_queued_getter():
    async def run():
        sleeping, retry = asyncio.Event(), asyncio.Event()
        async def sleep(seconds): sleeping.set(); await retry.wait()
        backend = Backend([RegisterReply("0", "22"), RegisterReply("33", "44")])
        async with native(backend=backend, sleep=sleep) as service:
            pending = asyncio.create_task(service.get_device_id())
            await asyncio.sleep(0)
            await service.start(allow_network=True)
            await sleeping.wait()
            assert not pending.done()
            assert await service.get_device_id() == "0"
            retry.set()
            await service.wait_worker()
            assert await pending == "33"
    asyncio.run(run())


def test_retry_schedule_advances_in_five_attempt_steps():
    async def run():
        delays = []
        async def sleep(seconds): delays.append(seconds); await asyncio.sleep(0)
        backend = Backend([*[RegisterReply(status=503)] * 7, RegisterReply("11", "22")])
        async with native(backend=backend, sleep=sleep) as service:
            await service.start(allow_network=True)
            await service.wait_worker()
            assert delays == [1,1,1,1,1,2,2]
            assert len([c for c in backend.calls if c[0] == "register"]) == 8
    asyncio.run(run())


def test_network_unavailable_suppresses_timer_and_restarts_when_available():
    async def run():
        backend = Backend([RegisterReply(net_error=-1), RegisterReply("11", "22")])
        async def forbidden(seconds): raise AssertionError("offline must not schedule a timer")
        async with native(backend=backend, sleep=forbidden) as service:
            await service.on_network_change(6)
            await service.start(allow_network=True)
            await service.wait_worker()
            assert service.waiting_network and not service.retry_delays
            await service.on_network_change(2)
            await service.wait_worker()
            assert await service.get_device_id() == "11"
            assert not service.waiting_network
    asyncio.run(run())


def test_network_change_during_request_does_not_duplicate_registration():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Gated(Backend):
            async def register(self, device_id, install_id):
                entered.set()
                await release.wait()
                return await super().register(device_id, install_id)
        backend = Gated()
        async with native(backend=backend) as service:
            await service.start(allow_network=True)
            await entered.wait()
            await service.on_network_change(2)
            release.set()
            await service.wait_worker()
            assert len([c for c in backend.calls if c[0] == "register"]) == 1
    asyncio.run(run())


def test_activation_transport_failure_after_early_delivery_does_not_reregister():
    async def run():
        backend = Backend(active=[ActiveReply(status=503)])
        async with native(backend=backend) as service:
            await service.start(allow_network=True)
            await service.wait_worker()
            assert await service.get_device_id() == "12345"
            assert not service.retry_delays
            assert service.last_error
    asyncio.run(run())


def test_deferred_activation_failure_retries_registration_and_activation():
    async def run():
        delays = []
        async def sleep(seconds): delays.append(seconds); await asyncio.sleep(0)
        backend = Backend([RegisterReply("11", "22"), RegisterReply("11", "22")],
                          [ActiveReply(status=503), ActiveReply()])
        async with native(backend=backend, flags_2=True, flags_3=True, sleep=sleep) as service:
            pending = asyncio.create_task(service.get_device_id())
            await asyncio.sleep(0)
            await service.start(allow_network=True)
            await service.wait_worker()
            assert await pending == "11" and delays == [1]
            assert len(backend.calls) == 4
    asyncio.run(run())


def test_cache_write_failure_keeps_memory_result_available():
    async def run():
        async def broken(record): raise OSError("synthetic cache failure")
        async with native(backend=Backend(), save_cache=broken) as service:
            await service.start(allow_network=True)
            await service.wait_worker()
            assert await service.get_device_id() == "12345"
            assert service.last_cache_error == "OSError"
    asyncio.run(run())


def test_native_mode_factory_and_http_adapter_use_only_mock_registration_endpoints(tmp_path):
    hardware = Hardware(UUID, "test-disk", "Model", "Brand", "CPU", "windows", "Windows Test", "10.0.19045")
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path.endswith("device_register/"):
            header = json.loads(gzip.decompress(request.content))["header"]
            assert header["device_id"] == header["install_id"] == 0
            return httpx.Response(200, json={"device_id_str": "11", "install_id_str": "22"})
        assert request.url.path.endswith("app_alert_check/")
        # Native activation callback does not require a successful JSON body.
        return httpx.Response(200, content=b"not JSON")
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = AhaDeviceService(IdentityStore(tmp_path / "profile.json"), http=client,
                                   hardware_reader=lambda: hardware)
        async def run():
            service = await adapter.start_native_mode(allow_network=True)
            try:
                await service.wait_worker()
                assert await service.get_device_id() == "11"
            finally:
                await service.close()
        asyncio.run(run())
    assert len(seen) == 2
    saved = adapter.store.load()
    assert DeviceRecord.load(saved.device_cache, UUID).device_id == "11"
    assert not saved.activated  # Native HTTP completion does not bypass login's stricter policy.


def test_sdk_callback_accepts_nondecimal_id_but_next_cache_load_rejects_it(tmp_path):
    hardware = Hardware(UUID, "test-disk", "Model", "Brand", "CPU", "windows", "Windows Test", "10.0.19045")
    adapter = AhaDeviceService(IdentityStore(tmp_path / "profile.json"), hardware_reader=lambda: hardware)
    async def run():
        core = await adapter.start_native_mode(allow_network=True, backend=Backend([RegisterReply("abc", "")]))
        try:
            await core.wait_worker()
            assert await core.get_device_id() == "abc"
        finally:
            await core.close()
    asyncio.run(run())
    restarted = AhaDeviceService(adapter.store, hardware_reader=lambda: hardware)
    assert restarted.get_device_id().device_id == "0"


def test_login_policy_still_rejects_native_cache_with_nonpositive_install_id(tmp_path):
    hardware = Hardware(UUID, "test-disk", "Model", "Brand", "CPU", "windows", "Windows Test", "10.0.19045")
    adapter = AhaDeviceService(IdentityStore(tmp_path / "profile.json"), hardware_reader=lambda: hardware)
    identity = adapter.get_device_id().identity
    identity.device_id, identity.install_id = "11", "0"
    identity.hardware_uuid, identity.registered, identity.activated = UUID, True, True
    identity.device_cache = DeviceRecord("11", "0", UUID).encoded(clock=1)
    adapter.store.save(identity)
    assert adapter.get_device_id().device_id == "11"
    with pytest.raises(ValueError, match="positive decimal"):
        adapter.get_device_id(require_activation=True)


def test_region_update_occurs_after_activation_dispatch_before_completion():
    async def run():
        order = []
        region_saved, release = asyncio.Event(), asyncio.Event()
        class Gated(Backend):
            async def activate(self, device_id, install_id):
                order.append("activation_dispatched")
                await release.wait()
                return await super().activate(device_id, install_id)
        async def cache(record): order.append("cache")
        async def region(country, source):
            order.append((country, source))
            region_saved.set()
        backend = Gated([RegisterReply("11", "22", region_record_ready=True, country_code="cn")])
        async with native(backend=backend, save_cache=cache, update_region=region) as service:
            await service.start(allow_network=True)
            await region_saved.wait()
            assert order == ["cache", "activation_dispatched", ("cn", "did")]
            assert service.region_record_ready and service.in_flight
            release.set()
            await service.wait_worker()
    asyncio.run(run())


def test_http_region_metadata_uses_did_default_and_persists_incoming_record(tmp_path):
    from trae2api.aha_tiny_storage import RegionRecord
    hardware = Hardware(UUID, "test-disk", "Model", "Brand", "CPU", "windows", "Windows Test", "10.0.19045")
    def handler(request):
        if request.url.path.endswith("device_register/"):
            return httpx.Response(200, json={"device_id_str": "11", "install_id_str": "22"},
                                  headers={"x-tt-store-region": "cn"})
        return httpx.Response(200)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = AhaDeviceService(IdentityStore(tmp_path / "profile.json"), http=client,
                                   hardware_reader=lambda: hardware)
        identity = adapter.get_device_id().identity
        identity.device_region = RegionRecord(True, "old", "cache", {"old": "query"}, {}).encoded(clock=1)
        adapter.store.save(identity)
        async def run():
            service = await adapter.start_native_mode(allow_network=True)
            try:
                await service.wait_worker()
                assert service.region_record_ready
            finally:
                await service.close()
        asyncio.run(run())
    stored = RegionRecord.load(adapter.store.load().device_region)
    assert stored == RegionRecord(True, "cn", "did")


@pytest.mark.parametrize("extra,expected_error", [(0,0), (1,-1)])
def test_native_http_response_size_limit(extra, expected_error):
    from trae2api.aha_native_backend import NativeHttpBackend, MAX_RESPONSE_SIZE
    hardware = Hardware(UUID, "disk", "Model", "Brand", "CPU", "windows", "Windows", "10.0.19045")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE_SIZE + extra)))) as client:
        backend = NativeHttpBackend(client, hardware, "3.4.20")
        result = asyncio.run(backend.activate("11", "22"))
    assert result.status == 200 and result.net_error == expected_error


def test_native_mode_uses_separate_local_id_after_wmi_fallback(tmp_path):
    hardware = Hardware(UUID.lower(), "disk", "Model", "Brand", "CPU", "windows", "Windows", "10.0.19045",
                        local_device_id="FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF")
    adapter = AhaDeviceService(IdentityStore(tmp_path / "profile.json"), hardware_reader=lambda: hardware)
    async def run():
        core = await adapter.start_native_mode()
        try:
            result = await core.resolve(timeout=0)
            assert result["deviceId"] == hardware.local_device_id
            assert result["remoteDeviceId"] == "0" and core.hardware_uuid == UUID.lower()
        finally:
            await core.close()
    asyncio.run(run())


def test_existing_async_facade_shares_native_mode_and_prevents_second_driver(tmp_path):
    hardware = Hardware(UUID, "disk", "Model", "Brand", "CPU", "windows", "Windows", "10.0.19045")
    adapter = AhaDeviceService(IdentityStore(tmp_path / "profile.json"), hardware_reader=lambda: hardware)
    async def run():
        service = await adapter.start_native_mode(allow_network=True, backend=Backend())
        try:
            assert await adapter.start_native_mode() is service
            await service.wait_worker()
            result = await adapter.get_device_id_async()
            assert result.device_id == result.remote_device_id == "12345"
            assert result.source == "native"
            resolved = await adapter.resolve_device_id_async()
            assert resolved.device_id == "12345"
            assert adapter.get_all_ids() == service.get_all_ids()
            assert adapter.get_device_id().device_id == "12345"
            with pytest.raises(ValueError, match="native mode active"):
                await adapter.register_device_async()
            with pytest.raises(ValueError, match="native mode active"):
                adapter.get_device_id(allow_network=True)
        finally:
            await service.close()
    asyncio.run(run())


@pytest.mark.parametrize("status,redirected_method", [(307,"POST"), (303,"GET")])
def test_native_http_adapter_follows_loader_redirects(status, redirected_method):
    from trae2api.aha_native_backend import NativeHttpBackend
    hardware = Hardware(UUID, "disk", "Model", "Brand", "CPU", "windows", "Windows", "10.0.19045")
    seen = []
    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(status, headers={"Location": "/native-result"})
        assert request.url.path == "/native-result" and request.method == redirected_method
        if redirected_method == "POST":
            assert json.loads(gzip.decompress(request.content))["magic_tag"] == "ss_app_log"
        return httpx.Response(200, json={"device_id_str": "11", "install_id_str": "22"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = asyncio.run(NativeHttpBackend(client, hardware, "3.4.20").register("", ""))
    assert result.device_id == "11" and len(seen) == 2


def test_native_redirect_limit_is_reported_as_nonzero_network_result():
    from trae2api.aha_native_backend import NativeHttpBackend
    hardware = Hardware(UUID, "disk", "Model", "Brand", "CPU", "windows", "Windows", "10.0.19045")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(302,
                            headers={"Location": "/loop"})), max_redirects=2) as client:
        result = asyncio.run(NativeHttpBackend(client, hardware, "3.4.20").register("", ""))
    assert result.net_error != 0 and result.device_id is None
