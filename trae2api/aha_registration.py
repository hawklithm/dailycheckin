"""Standalone Aha device registration based on the reviewed 3.4.20 binary.

Uses real local hardware. Does not read native login/cache files, rotate a login
token, or claim that arbitrary locally generated IDs are registered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
import zlib

import httpx

from .client_metadata import client_version
from .device_hardware import Hardware

REGISTER_URL = "https://log.snssdk.com/service/2/desktop/device_register/"
ACTIVE_URL = "https://log.snssdk.com/service/2/app_alert_check/"


@dataclass(frozen=True)
class Registration:
    device_id: str = field(repr=False)
    install_id: str = field(repr=False)
    region: str


def registration_request(hardware: Hardware, version: str, now: float | None = None) -> tuple[dict, bytes]:
    language = "zh-CN"  # Reviewed CN desktop initialization config.
    # Windows native config: appId=787976, package=com.trae.app, channel=stable.
    query = {"aid": "787976", "channel": "stable", "os": "Windows",
             "os_version": hardware.os_release, "device_platform": "PC",
             "version_code": version, "pc_uuid": hardware.pc_uuid, "pc_serial": hardware.pc_serial}
    offset = -(time.altzone if time.daylight and time.localtime().tm_isdst else time.timezone)
    header = {"device_id": 0, "install_id": 0, "aid": 787976, "os": "Windows",
              "device_platform": "PC", "mc": hardware.mac, "channel": "stable", "package": "com.trae.app",
              "language": language, "app_version": version, "os_version": hardware.os_release,
              "device_model": hardware.model, "time_zone": int(offset / 3600),
              "tz_name": time.tzname[time.localtime().tm_isdst > 0], "tz_offset": offset,
              "app_region": "CN", "app_language": language, "display_name": "Trae CN",
              "pc_uuid": hardware.pc_uuid, "pc_serial": hardware.pc_serial}
    body = {"header": header, "_gen_time": int((time.time() if now is None else now) * 1000),
            "magic_tag": "ss_app_log"}
    # RegisterDevice calls deflateInit2(-1, 8, 31, 9, 0): gzip framing,
    # default compression and memLevel=9. The HTTP transport must declare gzip;
    # live standalone validation returned zero IDs without Content-Encoding.
    compressor = zlib.compressobj(-1, zlib.DEFLATED, 31, 9, zlib.Z_DEFAULT_STRATEGY)
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return query, compressor.compress(raw) + compressor.flush()


def _response(response: httpx.Response, stage: str) -> dict:
    if response.status_code != 200:
        raise ValueError(f"device {stage} failed: HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise ValueError(f"device {stage} returned invalid JSON") from None
    if not isinstance(body, dict):
        raise ValueError(f"device {stage} returned an invalid object")
    return body


def register(client: httpx.Client, hardware: Hardware, version: str | None = None) -> Registration:
    version = version or client_version("3.4.20")
    query, body = registration_request(hardware, version)
    try:
        response = client.post(REGISTER_URL, params=query, content=body,
                               headers={"Content-Type": "application/json", "Content-Encoding": "gzip"}, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise ValueError(f"device registration network error ({type(exc).__name__}); not retried") from None
    result = _response(response, "registration")
    device_id, install_id = result.get("device_id_str"), result.get("install_id_str")
    if any(not isinstance(value, str) or not value.isdecimal() or int(value) <= 0
           for value in (device_id, install_id)):
        states = []
        for key in ("device_id", "install_id"):
            value = result.get(key)
            states.append(f"{key}=" + ("zero" if value == 0 else "present" if value is not None else "missing"))
        raise ValueError("device registration did not return valid device_id_str/install_id_str (" + ", ".join(states) + ")")
    region = response.headers.get("x-tt-store-region", "CN").upper()
    if region not in ("CN", "SG", "US", "USTTP"):
        raise ValueError("device registration returned an unsupported store region")
    return Registration(device_id, install_id, region)


def activate(client: httpx.Client, result: Registration, hardware: Hardware, version: str) -> None:
    query = {"aid": "787976", "app_name": "Trae CN", "version_code": version,
             "channel": "stable", "os": "Windows", "device_platform": "PC",
             "device_id": result.device_id, "iid": result.install_id,
             "pc_uuid": hardware.pc_uuid, "pc_serial": hardware.pc_serial}
    try:
        response = client.post(ACTIVE_URL, params=query, content=b"",
                               headers={"Content-Type": "application/json"}, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise ValueError(f"device activation network error ({type(exc).__name__}); not retried") from None
    body = _response(response, "activation")
    data = body.get("data")
    flag = data.get("is_activated") if isinstance(data, dict) else None
    if body.get("message") != "success" or type(flag) not in (bool, int) or flag != 1:
        raise ValueError("device activation was not confirmed")
