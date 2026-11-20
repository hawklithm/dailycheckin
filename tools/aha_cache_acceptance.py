"""Read-only native cache acceptance; prints comparisons, never IDs or keys."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.aha_native_oracle import NativeOracle
import httpx
from trae2api import device_hardware as hardware_api
from trae2api.aha_cache_codec import decode_base64, decode
from trae2api.aha_tiny_storage import NativeTinyStorage, DEVICE
from trae2api.aha_device_service import AhaDeviceService
from trae2api.login_identity import IdentityStore


def compare(image: Path, *, client_root: Path | None = None) -> dict:
    oracle = NativeOracle(image)
    storage = NativeTinyStorage.for_native_client(client_root=client_root)
    report = {"kind": "read_only_native_cache_comparison", "client_started": False,
              "live_service_calls": False, "credential_files_opened": False}
    if not storage.path.exists():
        return {**report, "cache_present": False}
    if storage.path.stat().st_size > 1024 * 1024:
        raise ValueError("acceptance input exceeds its read-only inspection limit")
    before = storage.path.read_bytes()
    encoded = storage.get(DEVICE)
    report["cache_present"] = encoded is not None
    if encoded is None:
        return report
    raw = decode_base64(encoded)
    if raw is None:
        return {**report, "native_base64_valid": False}
    original = oracle.decrypt(raw)
    python = decode(encoded)
    report["original_instruction_plaintext_equals_python"] = original == python
    data = json.loads(original)

    original_transport = httpx.HTTPTransport.handle_request
    original_writer = hardware_api._write_mac_cache
    suppressed = []
    def denied(*args, **kwargs):
        raise AssertionError("network forbidden during native cache acceptance")
    httpx.HTTPTransport.handle_request = denied
    hardware_api._write_mac_cache = lambda value: suppressed.append(True)
    try:
        hardware = hardware_api.Hardware.read_native()
        report["cache_format_version_matches"] = data.get("version") == "1.2"
        report["cache_uuid_matches_current_hardware"] = data.get("uuid") == hardware.pc_uuid
        parsed = oracle.uint64(data.get("device_id_str", ""))
        report["native_numeric_predicate_accepts_cached_id"] = parsed["ok"] and parsed["value"] != 0
        record = storage.load_device(hardware.pc_uuid)
        if record is not None:
            base = ROOT / "logs" / "aha-cache-acceptance"
            base.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=base) as folder:
                # Verify the eventual recursive cleanup's exact target.
                if Path(folder).resolve().parent != base.resolve():
                    raise ValueError("temporary profile escaped acceptance workspace")
                adapter = AhaDeviceService(IdentityStore(Path(folder) / "profile.json"),
                                           hardware_reader=lambda: hardware)
                async def run():
                    core = await adapter.start_native_mode(storage=storage)
                    try:
                        result = await adapter.get_device_id_async()
                        resolved = await adapter.resolve_device_id_async()
                        return (result.device_id == data["device_id_str"],
                                resolved.device_id == data["device_id_str"],
                                adapter.get_all_ids()["deviceId"] == data["device_id_str"])
                    finally:
                        await core.close()
                getter, wrapper, all_ids = asyncio.run(run())
            report.update(python_getter_equals_original_cached_id=getter,
                          public_facade_resolver_equals_original_cached_id=wrapper,
                          public_facade_all_ids_equal_original_cached_id=all_ids)
        else:
            report["python_getter_equals_original_cached_id"] = None  # cache miss, not a comparison
        report["original_cache_unchanged"] = storage.path.read_bytes() == before
        report["hardware_cache_write_attempts_suppressed"] = len(suppressed)
        report["real_device_identifiers_in_report"] = False
        return report
    finally:
        httpx.HTTPTransport.handle_request = original_transport
        hardware_api._write_mac_cache = original_writer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--client-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = compare(args.image, client_root=args.client_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not (report.get("python_getter_equals_original_cached_id")
            and report.get("original_cache_unchanged")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
