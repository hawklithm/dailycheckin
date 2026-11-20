"""Results from original pinned PE instructions, with synthetic inputs only."""
import json
from pathlib import Path

import pytest

from trae2api.aha_cache_codec import decode_base64, decrypt, encrypt, decode, encode
from trae2api.aha_device_cache import DeviceRecord
from trae2api.aha_native_semantics import parse_uint64, needs_registration, retry_delay_ms, migrate_old_id

VECTORS = json.loads((Path(__file__).parent / "fixtures/aha_native_oracle_20261120.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS["uint64"])
def test_original_uint64(case):
    actual = parse_uint64(case["input"])
    assert (actual.ok, actual.value) == (case["ok"], case["value"])


@pytest.mark.parametrize("case", VECTORS["startup_policy"])
def test_original_startup_policy(case):
    assert needs_registration(case["device_id"], case["region"], case["region_record_ready"]) == case["needs_registration"]


@pytest.mark.parametrize("case", VECTORS["retry_delay"])
def test_original_retry_delay(case):
    assert retry_delay_ms(case["attempt"]) == case["delay_ms"]


@pytest.mark.parametrize("case", VECTORS["header_number"])
def test_original_registration_header_double(case):
    assert float(parse_uint64(case["input"]).value) == case["double"]


@pytest.mark.parametrize("case", VECTORS["base64"])
def test_original_strict_base64(case):
    result = decode_base64(case["input"])
    assert (result is not None) == case["ok"]
    if result is not None:
        assert result.hex() == case["decoded_hex"]


@pytest.mark.parametrize("case", VECTORS["migration"])
def test_original_old_id_migration(case):
    result = migrate_old_id(case["current"], case["old"])
    assert (result.accepted, result.device_id, result.old_device_id, result.write_cache) == (
        case["accepted"], case["device_id"], case["old_device_id"], case["write_cache"])


@pytest.mark.parametrize("case", VECTORS["codec"])
def test_original_cache_cipher(case):
    plain, encrypted = bytes.fromhex(case["plaintext_hex"]), bytes.fromhex(case["encrypted_hex"])
    assert encrypt(plain, clock=case["clock"]) == encrypted
    assert decrypt(encrypted) == bytes.fromhex(case["decrypted_hex"])


@pytest.mark.parametrize("case", VECTORS["codec_decryption"])
def test_original_legacy_and_invalid_cipher(case):
    assert decrypt(bytes.fromhex(case["encrypted_hex"])) == bytes.fromhex(case["decoded_hex"])


def test_device_record_accepts_native_plus_sign_and_rejects_overflow():
    record = DeviceRecord("+0001", "", "test-uuid")
    assert DeviceRecord.load(record.encoded(clock=1700000000), "test-uuid") == record
    too_large = DeviceRecord("18446744073709551616", "2", "test-uuid")
    assert DeviceRecord.load(too_large.encoded(clock=1700000000), "test-uuid") is None


def test_cache_envelope_invalid_input_returns_empty_and_never_opens_files():
    assert decode("not base64") == b""
    assert decode("====") == b""
    assert decode(encode(b"record", clock=1700000000)) == b"record"
