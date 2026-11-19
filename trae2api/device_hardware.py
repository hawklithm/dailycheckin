"""Read the real Windows device fields needed by standalone registration."""
from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
import platform
import struct
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


def uuid_from_smbios(data: bytes) -> str:
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
            if raw not in (b"\0" * 16, b"\xff" * 16):
                return str(uuid.UUID(bytes_le=raw)).upper()
        strings_end = data.find(b"\0\0", pos + size, end)
        if strings_end < 0 or kind == 127:
            break
        pos = strings_end + 2
    raise ValueError("no valid hardware UUID in SMBIOS")


def system_uuid() -> str:
    if platform.system() != "Windows":
        raise ValueError("standalone device registration currently supports Windows hardware only")
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
    return uuid_from_smbios(buffer.raw)


def disk_serial() -> str:
    """Match the native first attempt: PhysicalDrive0 storage descriptor."""
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
    handle = kernel.CreateFileW(r"\\.\PhysicalDrive0", 0, 3, None, 3, 0, None)
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


def mac_address() -> str:
    """First nonempty GetAdaptersAddresses physical address, uppercase/dashes."""
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

    @classmethod
    def read(cls) -> "Hardware":
        name, version = os_metadata()
        return cls(system_uuid(), disk_serial(), device_model(), manufacturer(), cpu_brand(),
                   name, version, platform.version() if name == "windows" else platform.release(), mac_address())
