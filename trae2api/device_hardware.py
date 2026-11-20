"""Read the real Windows device fields needed by standalone registration."""
from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
import json
import platform
import struct
import subprocess
import uuid

from .client_metadata import device_model, os_metadata


def registry_text(path: str, name: str) -> str:
    if platform.system() != "Windows":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
        return value.strip() if isinstance(value, str) else ""
    except OSError:
        return ""


def manufacturer() -> str:
    return registry_text(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemManufacturer")


def cpu_brand() -> str:
    return registry_text(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")


def uuid_from_smbios(data: bytes, *, allow_unset: bool = False) -> str:
    """Parse RawSMBIOSData and the type-1 UUID using native Windows byte order."""
    if len(data) < 8:
        raise ValueError("invalid SMBIOS firmware data")
    length = struct.unpack_from("<I", data, 4)[0]
    if length > len(data) - 8:
        raise ValueError("truncated SMBIOS firmware data")
    pos, end = 8, 8 + length
    while pos + 4 <= end:
        kind, size = data[pos], data[pos + 1]
        if size < 4 or pos + size > end:
            break
        if kind == 1 and size >= 25:
            raw = data[pos + 8:pos + 24]
            if allow_unset or raw not in (b"\0" * 16, b"\xff" * 16):
                return str(uuid.UUID(bytes_le=raw)).upper()
        strings_end = data.find(b"\0\0", pos + size, end)
        if strings_end < 0 or kind == 127:
            break
        pos = strings_end + 2
    raise ValueError("no valid hardware UUID in SMBIOS")


def _smbios_uuid() -> str:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    firmware = kernel.GetSystemFirmwareTable
    firmware.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    firmware.restype = ctypes.c_uint32
    provider = int.from_bytes(b"RSMB", "big")
    size = firmware(provider, 0, None, 0)
    if not size or size > 16 * 1024 * 1024:
        raise ValueError("cannot read SMBIOS hardware UUID")
    buffer = ctypes.create_string_buffer(size)
    read = firmware(provider, 0, buffer, size)
    if read != size:
        raise ValueError("SMBIOS hardware information changed while reading")
    return uuid_from_smbios(buffer.raw, allow_unset=True)


def _wmi_uuid() -> str | None:
    # Fixed, read-only query. Never interpolate hardware values into a shell.
    command = ("$ErrorActionPreference='Stop'; "
               "Get-CimInstance -Query 'SELECT UUID FROM Win32_ComputerSystemProduct' | "
               "Select-Object -First 1 -ExpandProperty UUID | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, timeout=15, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        value = json.loads(result.stdout.decode("utf-8-sig"))
        return value if isinstance(value, str) else None
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
        return None


def device_uuids() -> tuple[str, str]:
    """Registration UUID may use WMI; localDeviceId keeps DeviceInfo's UUID."""
    if platform.system() != "Windows":
        raise ValueError("standalone device registration currently supports Windows hardware only")
    try:
        local = _smbios_uuid()
    except (OSError, ValueError):
        local = ""
    try:
        parsed = uuid.UUID(local)
        local = str(parsed).upper()
        if parsed.int not in (0, (1 << 128) - 1):
            return local, local
    except ValueError:
        pass
    # Native checks VT_BSTR, converts UTF-16 to UTF-8, then copies verbatim.
    # A failed WMI lookup retains the original DeviceInfo UUID.
    fallback = _wmi_uuid()
    return (fallback if fallback is not None else local), local


def system_uuid() -> str:
    value, _ = device_uuids()
    if not value:
        raise ValueError("cannot read a hardware UUID from SMBIOS or WMI")
    return value


def _disk_serial_from_drive(index: int) -> str:
    if platform.system() != "Windows":
        return ""
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(r"\\.\PhysicalDrive" + str(index), 0, 3, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return ""
    try:
        query = ctypes.create_string_buffer(12)  # StorageDeviceProperty, PropertyStandardQuery.
        output = ctypes.create_string_buffer(4096)
        returned = wintypes.DWORD()
        if not kernel.DeviceIoControl(handle, 0x2D1400, query, len(query), output,
                                      len(output), ctypes.byref(returned), None) or returned.value < 28:
            return ""
        offset = struct.unpack_from("<I", output.raw, 24)[0]
        if offset < 36 or offset >= returned.value:
            return ""
        return output.raw[offset:returned.value].split(b"\0")[0].decode("ascii", errors="ignore").strip()
    finally:
        kernel.CloseHandle(handle)


def _disk_count() -> int:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\disk\Enum") as key:
            value, kind = winreg.QueryValueEx(key, "Count")
        return min(value, 10) if kind == winreg.REG_DWORD and type(value) is int and value > 0 else 0
    except OSError:
        return 0


def _os_disk_number() -> int:
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    directory = ctypes.create_unicode_buffer(32768)
    length = kernel.GetWindowsDirectoryW(directory, len(directory))
    if not 2 <= length < len(directory) or directory.value[1] != ":":
        return -1
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW("\\\\.\\" + directory.value[:2], 0, 3, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return -1
    try:
        output, returned = ctypes.create_string_buffer(4096), wintypes.DWORD()
        if (kernel.DeviceIoControl(handle, 0x560000, None, 0, output, len(output),
                                   ctypes.byref(returned), None) and returned.value >= 32
                and struct.unpack_from("<I", output.raw)[0]):
            return struct.unpack_from("<I", output.raw, 8)[0]
        return -1
    finally:
        kernel.CloseHandle(handle)


def disk_serial() -> str:
    """Enumerate up to ten disks; prefer disk 0, OS disk, then first valid disk."""
    if platform.system() != "Windows":
        return ""
    serials = {index: _disk_serial_from_drive(index) for index in range(_disk_count())}
    if serials.get(0):
        return serials[0]
    system_disk = _os_disk_number() if serials else -1
    if serials.get(system_disk):
        return serials[system_disk]
    return next((value for value in serials.values() if value), "")


MAC_CACHE_KEY = r"Software\DeviceInfo\MacAddr"


def _read_mac_cache() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MAC_CACHE_KEY) as key:
            value, kind = winreg.QueryValueEx(key, "mac")
        if kind == winreg.REG_BINARY and isinstance(value, bytes) and 0 < len(value) <= 256:
            return value.decode("ascii")
        return ""
    except (OSError, UnicodeError):
        return ""


def _write_mac_cache(value: str) -> None:
    import winreg
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, MAC_CACHE_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "mac", 0, winreg.REG_BINARY, value.encode("ascii"))
    except OSError:
        pass  # Native also continues with the sampled address if caching fails.


def mac_address() -> str:
    """Native HKCU cache first, then adapters; persist a real sampled address."""
    if platform.system() != "Windows":
        return ""
    cached = _read_mac_cache()
    if cached:
        return cached
    value = _adapter_mac_address()
    if value:
        _write_mac_cache(value)
    return value


def _adapter_mac_address() -> str:
    if platform.system() != "Windows":
        return ""
    api = ctypes.WinDLL("iphlpapi").GetAdaptersAddresses
    api.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_ulong)]
    api.restype = ctypes.c_ulong
    size = ctypes.c_ulong(15000)
    buffer = ctypes.create_string_buffer(size.value)
    result = api(0, 0, None, buffer, ctypes.byref(size))
    if result == 111 and size.value <= 1024 * 1024:
        buffer = ctypes.create_string_buffer(size.value)
        result = api(0, 0, None, buffer, ctypes.byref(size))
    if result:
        return ""
    pointer = ctypes.addressof(buffer)
    end = pointer + len(buffer)
    visited = set()
    while pointer and pointer not in visited and ctypes.addressof(buffer) <= pointer <= end - 96:
        visited.add(pointer)
        row = ctypes.string_at(pointer, 96)
        length = struct.unpack_from("<I", row, 88)[0]
        if 0 < length <= 8:
            address = row[80:80 + length]
            if any(address):
                return "-".join(f"{byte:02X}" for byte in address)
        pointer = struct.unpack_from("<Q", row, 8)[0]
    return ""


@dataclass(frozen=True)
class Hardware:
    pc_uuid: str = field(repr=False)
    pc_serial: str = field(repr=False)
    model: str
    brand: str
    cpu: str
    os_name: str
    os_version: str
    os_release: str
    mac: str = field(default="", repr=False)
    local_device_id: str | None = field(default=None, repr=False)

    @classmethod
    def read(cls) -> "Hardware":
        result = cls.read_native()
        if not result.pc_uuid:
            raise ValueError("cannot read a hardware UUID from SMBIOS or WMI")
        return result

    @classmethod
    def read_native(cls) -> "Hardware":
        name, version = os_metadata()
        registration_uuid, local_uuid = device_uuids()
        return cls(registration_uuid, disk_serial(), device_model(), manufacturer(), cpu_brand(),
                   name, version, platform.version() if name == "windows" else platform.release(),
                   mac_address(), local_uuid)
