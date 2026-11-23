"""Offline virtual SMBIOS UUID candidates, not Aha registered device IDs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid


def format_smbios_uuid(raw: bytes) -> str:
    """Match the Windows device-info UUID byte order found in the binary."""
    if len(raw) != 16:
        raise ValueError("SMBIOS UUID must be exactly 16 bytes")
    return str(uuid.UUID(bytes_le=raw)).upper()


def get_or_create_profile(directory: Path, account_id: str) -> dict:
    """Persist one virtual SMBIOS value per explicit account identifier.

    The generated value is only a candidate for local testing. This does not
    perform Aha registration or prove acceptance by any remote service.
    """
    if not account_id or not account_id.strip():
        raise ValueError("account ID must not be empty")
    key = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (key + ".json")
    if not target.exists():
        raw = uuid.uuid4().bytes_le
        profile = {"version": 1, "account_key_sha256": key,
                   "source": "synthetic_smbios_uuid_unregistered",
                   "smbios_uuid_le_hex": raw.hex(),
                   "local_device_id_candidate": format_smbios_uuid(raw)}
        fd, temp_name = tempfile.mkstemp(prefix=".device-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
                f.write("\n")
            try:
                os.link(temp_name, target)
            except FileExistsError:
                pass
        finally:
            os.unlink(temp_name)
    data = json.loads(target.read_text(encoding="utf-8"))
    if data.get("version") != 1 or data.get("account_key_sha256") != key or data.get("source") != "synthetic_smbios_uuid_unregistered":
        raise ValueError("invalid device profile")
    try:
        raw = bytes.fromhex(data["smbios_uuid_le_hex"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid SMBIOS UUID in device profile") from exc
    if data.get("local_device_id_candidate") != format_smbios_uuid(raw):
        raise ValueError("device profile UUID mismatch")
    return data


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create or read an offline virtual device candidate")
    parser.add_argument("--account-id", required=True, help="stable non-secret account identifier")
    parser.add_argument("--directory", required=True, type=Path, help="directory for persistent profiles")
    args = parser.parse_args(argv)
    try:
        profile = get_or_create_profile(args.directory, args.account_id)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"device profile error: {exc}\n")
    print(json.dumps({"local_device_id_candidate": profile["local_device_id_candidate"],
                      "registered": False, "server_accepted": "unknown"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
