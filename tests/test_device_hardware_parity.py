"""Offline Windows hardware fallback tests; never access real WMI/registry."""
from contextlib import nullcontext
import json
import sys
from types import SimpleNamespace

import pytest

from trae2api import device_hardware as hw

UUID = "33221100-5544-7766-8899-AABBCCDDEEFF"


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(hw.platform, "system", lambda: "Windows")
    def denied(*args, **kwargs):
        raise AssertionError("real subprocess forbidden")
    monkeypatch.setattr(hw.subprocess, "run", denied)


def registry(monkeypatch, value, kind=3, create_error=False):
    seen = []
    def create(*args):
        if create_error:
            raise PermissionError("synthetic access denied")
        seen.append(("create", args))
        return nullcontext("key")
    fake = SimpleNamespace(HKEY_CURRENT_USER="HKCU", HKEY_LOCAL_MACHINE="HKLM", REG_SZ=1, REG_BINARY=3,
        REG_DWORD=4, KEY_SET_VALUE=2, OpenKey=lambda *a: nullcontext("key"),
        QueryValueEx=lambda *a: (value, kind), CreateKeyEx=create,
        SetValueEx=lambda *a: seen.append(("set", a)))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    return seen


def test_smbios_is_preferred_and_uuid_is_uppercase(monkeypatch):
    monkeypatch.setattr(hw, "_smbios_uuid", lambda: UUID.lower())
    def forbidden():
        raise AssertionError("WMI not needed")
    monkeypatch.setattr(hw, "_wmi_uuid", forbidden)
    assert hw.system_uuid() == UUID


@pytest.mark.parametrize("invalid", ["", "invalid", "00000000-0000-0000-0000-000000000000",
                                    "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"])
def test_invalid_smbios_falls_back_to_wmi(monkeypatch, invalid):
    monkeypatch.setattr(hw, "_smbios_uuid", lambda: invalid)
    monkeypatch.setattr(hw, "_wmi_uuid", lambda: UUID)
    assert hw.system_uuid() == UUID


def test_smbios_read_failure_falls_back_to_wmi(monkeypatch):
    def broken():
        raise OSError("synthetic firmware failure")
    monkeypatch.setattr(hw, "_smbios_uuid", broken)
    monkeypatch.setattr(hw, "_wmi_uuid", lambda: UUID)
    assert hw.system_uuid() == UUID


def test_missing_uuid_does_not_invent_hardware(monkeypatch):
    monkeypatch.setattr(hw, "_smbios_uuid", lambda: "")
    monkeypatch.setattr(hw, "_wmi_uuid", lambda: "")
    with pytest.raises(ValueError, match="SMBIOS or WMI"):
        hw.system_uuid()


def test_wmi_uuid_is_copied_verbatim_while_local_uuid_keeps_smbios(monkeypatch):
    unset = "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"
    monkeypatch.setattr(hw, "_smbios_uuid", lambda: unset)
    monkeypatch.setattr(hw, "_wmi_uuid", lambda: UUID.lower())
    assert hw.device_uuids() == (UUID.lower(), unset)
    assert hw.system_uuid() == UUID.lower()


def test_failed_wmi_preserves_original_unset_smbios_uuid(monkeypatch):
    unset = "00000000-0000-0000-0000-000000000000"
    monkeypatch.setattr(hw, "_smbios_uuid", lambda: unset)
    monkeypatch.setattr(hw, "_wmi_uuid", lambda: None)
    assert hw.device_uuids() == (unset, unset)


def test_empty_wmi_bstr_is_distinct_from_failed_wmi_query(monkeypatch):
    unset = "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"
    monkeypatch.setattr(hw, "_smbios_uuid", lambda: unset)
    monkeypatch.setattr(hw, "_wmi_uuid", lambda: "")
    assert hw.device_uuids() == ("", unset)


def test_wmi_uses_fixed_read_query_hidden_process_and_timeout(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=json.dumps(UUID).encode())
    monkeypatch.setattr(hw.subprocess, "run", run)
    assert hw._wmi_uuid() == UUID
    argv, options = calls[0]
    assert "SELECT UUID FROM Win32_ComputerSystemProduct" in argv[-1]
    assert "-NonInteractive" in argv and options["timeout"] == 15
    assert options["creationflags"] == hw.subprocess.CREATE_NO_WINDOW


@pytest.mark.parametrize("count,kind,expected", [(3,4,3), (99,4,10), (0,4,0), (-1,4,0), ("4",1,0)])
def test_disk_count_uses_native_registry_cap(monkeypatch, count, kind, expected):
    registry(monkeypatch, count, kind)
    assert hw._disk_count() == expected


@pytest.mark.parametrize("serials,system_disk,expected", [
    (["disk0", "disk1", "disk2"], 2, "disk0"),
    (["", "disk1", "disk2"], 2, "disk2"),
    (["", "disk1", ""], 2, "disk1"),
    (["", "", ""], -1, ""),
    ([], -1, ""),
])
def test_disk_selection_order(monkeypatch, serials, system_disk, expected):
    seen = []
    monkeypatch.setattr(hw, "_disk_count", lambda: len(serials))
    def sample(index):
        seen.append(index)
        return serials[index]
    monkeypatch.setattr(hw, "_disk_serial_from_drive", sample)
    monkeypatch.setattr(hw, "_os_disk_number", lambda: system_disk)
    assert hw.disk_serial() == expected
    assert seen == list(range(len(serials)))


def test_mac_cached_value_is_preserved_without_resampling(monkeypatch):
    registry(monkeypatch, b"a-cached-native-value")
    def forbidden():
        raise AssertionError("adapters must not be sampled with cache present")
    monkeypatch.setattr(hw, "_adapter_mac_address", forbidden)
    assert hw.mac_address() == "a-cached-native-value"


def test_mac_cache_miss_samples_and_persists_real_adapter_value(monkeypatch):
    seen = registry(monkeypatch, b"")
    monkeypatch.setattr(hw, "_adapter_mac_address", lambda: "00-11-22-33-44-55")
    assert hw.mac_address() == "00-11-22-33-44-55"
    assert seen[0][1][0:2] == ("HKCU", hw.MAC_CACHE_KEY)
    assert seen[1][1] == ("key", "mac", 0, 3, b"00-11-22-33-44-55")


def test_mac_wrong_registry_type_is_a_miss(monkeypatch):
    registry(monkeypatch, "cached-but-wrong-type", kind=1)
    monkeypatch.setattr(hw, "_adapter_mac_address", lambda: "00-11-22-33-44-55")
    assert hw.mac_address() == "00-11-22-33-44-55"


def test_mac_cache_write_failure_keeps_sampled_value(monkeypatch):
    registry(monkeypatch, b"", create_error=True)
    monkeypatch.setattr(hw, "_adapter_mac_address", lambda: "00-11-22-33-44-55")
    assert hw.mac_address() == "00-11-22-33-44-55"


def test_no_mac_does_not_write_cache(monkeypatch):
    seen = registry(monkeypatch, b"")
    monkeypatch.setattr(hw, "_adapter_mac_address", lambda: "")
    assert hw.mac_address() == ""
    assert not seen
