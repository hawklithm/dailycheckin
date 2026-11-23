import json

import pytest

from trae2api.device_identity import format_smbios_uuid, get_or_create_profile


def test_format_matches_native_smbios_byte_order():
    assert format_smbios_uuid(bytes.fromhex("00112233445566778899aabbccddeeff")) == (
        "33221100-5544-7766-8899-AABBCCDDEEFF"
    )
    with pytest.raises(ValueError):
        format_smbios_uuid(b"short")


def test_profile_stable_distinct_and_no_account_plaintext(tmp_path):
    first = get_or_create_profile(tmp_path, "account-A")
    assert get_or_create_profile(tmp_path, "account-A") == first
    second = get_or_create_profile(tmp_path, "account-B")
    assert first["local_device_id_candidate"] != second["local_device_id_candidate"]
    assert "account-A" not in next(p for p in tmp_path.iterdir() if first["account_key_sha256"] in p.name).read_text()


def test_profile_corruption_fails_closed(tmp_path):
    profile = get_or_create_profile(tmp_path, "account-A")
    path = tmp_path / (profile["account_key_sha256"] + ".json")
    profile["local_device_id_candidate"] = "incorrect"
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="mismatch"):
        get_or_create_profile(tmp_path, "account-A")


def test_empty_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        get_or_create_profile(tmp_path, "  ")
