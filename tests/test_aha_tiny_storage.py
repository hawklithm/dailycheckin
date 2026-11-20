"""Native cache container interoperability using temporary synthetic files."""
import asyncio
import json

import pytest

from trae2api.aha_cache_codec import encode
from trae2api.aha_device_cache import DeviceRecord
from trae2api.aha_device_service import AhaDeviceService
from trae2api.aha_tiny_storage import NativeTinyStorage, RegionRecord, PREF, DEVICE, REGION
from trae2api.device_hardware import Hardware
from trae2api.login_identity import IdentityStore

UUID = "33221100-5544-7766-8899-AABBCCDDEEFF"


def test_native_container_roundtrip_preserves_other_preferences(tmp_path):
    path = tmp_path / "TinyStorage"
    path.write_text(json.dumps({"another_pref": "keep", PREF: {"another_key": "keep"}}))
    store = NativeTinyStorage(path, writable=True)
    record = DeviceRecord("11", "22", UUID)
    store.save_device(record)
    store.save_region(RegionRecord(True, "cn", "did", {}, {"x-test": "value"}))
    data = json.loads(path.read_text())
    assert data["another_pref"] == data[PREF]["another_key"] == "keep"
    assert isinstance(data[PREF][DEVICE], str) and isinstance(data[PREF][REGION], str)
    assert store.load_device(UUID) == record
    assert store.load_device("other-hardware") is None
    assert store.load_region() == RegionRecord(True, "cn", "did", {}, {"x-test": "value"})


def test_native_storage_is_read_only_by_default(tmp_path):
    path = tmp_path / "TinyStorage"
    NativeTinyStorage(path, writable=True).save_device(DeviceRecord("11", "22", UUID))
    before = path.read_bytes()
    store = NativeTinyStorage(path)
    assert store.load_device(UUID).device_id == "11"
    with pytest.raises(PermissionError, match="read-only"):
        store.save_device(DeviceRecord("33", "44", UUID))
    assert path.read_bytes() == before


@pytest.mark.parametrize("contents", ["broken JSON", "null", "[]", '{"tiny_storage_data":null}',
                                     '{"tiny_storage_data":{"aha.device.device_id":123}}'])
def test_invalid_native_container_is_a_device_cache_miss(tmp_path, contents):
    path = tmp_path / "TinyStorage"
    path.write_text(contents)
    store = NativeTinyStorage(path)
    assert store.load_device(UUID) is None
    assert not store.load_region().ready
    assert path.read_text() == contents


def test_region_readiness_means_parsed_dictionary_not_required_country_fields():
    assert RegionRecord.load(encode(b"{}", clock=1)) == RegionRecord(ready=True)
    assert not RegionRecord.load(encode(b"[]", clock=1)).ready
    value = {"countryCode": 12, "countryCodeSrc": "did", "query": {"a": "b", "bad": 123}, "headers": []}
    result = RegionRecord.load(encode(json.dumps(value).encode(), clock=1))
    assert result == RegionRecord(True, "", "did", {"a": "b"}, None)


def test_native_mode_explicit_storage_supplies_same_id_without_registration(tmp_path):
    path = tmp_path / "TinyStorage"
    NativeTinyStorage(path, writable=True).save_device(DeviceRecord("11", "22", UUID))
    before = path.read_bytes()
    hardware = Hardware(UUID, "test-disk", "Model", "Brand", "CPU", "windows", "Windows Test", "10.0.19045")
    adapter = AhaDeviceService(IdentityStore(tmp_path / "profile.json"), hardware_reader=lambda: hardware)
    async def run():
        service = await adapter.start_native_mode(storage=NativeTinyStorage(path))
        try:
            assert await service.get_device_id() == "11"
            assert (await service.resolve())["deviceId"] == "11"
        finally:
            await service.close()
    asyncio.run(run())
    assert path.read_bytes() == before


def test_legacy_preferences_root_device_overrides_nested_copy(tmp_path):
    nested, top = DeviceRecord("11", "22", UUID), DeviceRecord("33", "44", UUID)
    old = tmp_path / "Preferences"
    old.write_text(json.dumps({PREF: {DEVICE: nested.encoded(clock=1), "other": "keep"},
                               DEVICE: top.encoded(clock=1)}))
    original = old.read_bytes()
    target = tmp_path / "TinyStorage"
    store = NativeTinyStorage(target, writable=True, legacy_preferences=old)
    assert store.load_device(UUID) == top
    assert store.get("other") == "keep"
    assert old.read_bytes() == original
    assert PREF in json.loads(target.read_text())


def test_existing_new_preferences_suppress_legacy_migration(tmp_path):
    target, old = tmp_path / "TinyStorage", tmp_path / "Preferences"
    target.write_text(json.dumps({PREF: {}}))
    old.write_text(json.dumps({DEVICE: DeviceRecord("11", "22", UUID).encoded(clock=1)}))
    before = target.read_bytes()
    assert NativeTinyStorage(target, writable=True, legacy_preferences=old).load_device(UUID) is None
    assert target.read_bytes() == before


def test_read_only_legacy_migration_view_does_not_create_target(tmp_path):
    target, old = tmp_path / "TinyStorage", tmp_path / "Preferences"
    old.write_text(json.dumps({DEVICE: DeviceRecord("11", "22", UUID).encoded(clock=1)}))
    assert NativeTinyStorage(target, legacy_preferences=old).load_device(UUID).device_id == "11"
    assert not target.exists()


def test_region_memory_update_keeps_omitted_optional_maps():
    current = RegionRecord(True, "old", "cache", {"query": "old"}, {"header": "old"})
    updated = current.updated(RegionRecord(True, "new", "did"))
    assert updated == RegionRecord(True, "new", "did", current.query, current.headers)
    assert current.updated(RegionRecord(True, "new", "did", {}, {})).query == {}


def test_default_native_layout_migrates_preferences_without_writing_by_default(tmp_path):
    old = tmp_path / "Preferences"
    old.write_text(json.dumps({DEVICE: DeviceRecord("11", "22", UUID).encoded(clock=1)}))
    source = NativeTinyStorage.for_native_client(client_root=tmp_path)
    assert source.path == tmp_path / "aha/TinyStorage"
    assert source.load_device(UUID).device_id == "11"
    assert not source.path.exists()


def test_explicit_legacy_path_takes_precedence_over_native_default(tmp_path):
    (tmp_path / "Preferences").write_text(json.dumps({DEVICE: DeviceRecord("11", "22", UUID).encoded(clock=1)}))
    override = tmp_path / "old-copy"
    override.write_text(json.dumps({DEVICE: DeviceRecord("33", "44", UUID).encoded(clock=1)}))
    source = NativeTinyStorage(tmp_path / "aha/TinyStorage", legacy_preferences=override)
    assert source.load_device(UUID).device_id == "33"
