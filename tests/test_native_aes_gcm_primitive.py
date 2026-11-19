"""Synthetic-only tests for the isolated local AES-GCM byte primitive."""
from __future__ import annotations

import base64
import contextlib
import io
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tools.native_aes_gcm_primitive import (
    MAX_UNIX_SECONDS,
    derive_local_aes256_key,
    encode_local_gcm_payload,
)


class NativeAesGcmPrimitiveTests(unittest.TestCase):
    def test_fixed_vector_and_round_trip(self) -> None:
        seed = bytes(range(32))
        salt = bytes(8)
        nonce = bytes(range(12))
        unix_seconds = 1_700_000_000
        payload = b"synthetic payload for fixed vector"
        expected = (
            b"AAECAwQFBgcICQoLNHu4b62AtnLuYefqyIUXDOf24VuCWzkVQAKBpWsMY8ZuYt4f2Y2+kHscuSPeEeKjHTE="
        )

        key = derive_local_aes256_key(seed, salt)
        encoded = encode_local_gcm_payload(
            seed=seed, salt=salt, nonce=nonce,
            unix_seconds=unix_seconds, payload=payload,
        )

        self.assertEqual(key, bytes(range(32)))
        self.assertEqual(encoded, expected)
        decoded = base64.b64decode(encoded, validate=True)
        self.assertEqual(len(decoded), len(nonce) + len(payload) + 16)
        self.assertEqual(decoded[:12], nonce)
        self.assertEqual(base64.b64encode(decoded), encoded)
        self.assertEqual(
            AESGCM(key).decrypt(nonce, decoded[12:], str(unix_seconds).encode("ascii")),
            payload,
        )

    def test_key_derivation_xors_only_the_first_eight_bytes(self) -> None:
        seed = bytes(range(32))
        salt = bytes.fromhex("a0a1a2a3a4a5a6a7")
        expected = bytes(seed[i] ^ salt[i] for i in range(8)) + seed[8:]
        self.assertEqual(derive_local_aes256_key(seed, salt), expected)

    def test_timestamp_is_authenticated_data(self) -> None:
        common = {
            "seed": bytes(range(32)), "salt": bytes(range(8)),
            "nonce": bytes(range(12)), "payload": b"synthetic timestamp binding",
        }
        first = encode_local_gcm_payload(**common, unix_seconds=1_700_000_000)
        second = encode_local_gcm_payload(**common, unix_seconds=1_700_000_001)
        first_raw = base64.b64decode(first, validate=True)
        second_raw = base64.b64decode(second, validate=True)

        self.assertEqual(first_raw[:12], second_raw[:12])
        self.assertEqual(first_raw[12:-16], second_raw[12:-16])
        self.assertNotEqual(first_raw[-16:], second_raw[-16:])
        key = derive_local_aes256_key(common["seed"], common["salt"])
        with self.assertRaises(InvalidTag):
            AESGCM(key).decrypt(common["nonce"], first_raw[12:], b"1700000001")

    def test_salt_changes_key_and_ciphertext(self) -> None:
        common = {
            "seed": bytes(range(32)), "nonce": bytes(range(12)),
            "unix_seconds": 1_700_000_000, "payload": b"synthetic salt binding",
        }
        salt_a = bytes(8)
        salt_b = b"\x01" + bytes(7)
        key_a = derive_local_aes256_key(common["seed"], salt_a)
        key_b = derive_local_aes256_key(common["seed"], salt_b)
        encoded_a = encode_local_gcm_payload(**common, salt=salt_a)
        encoded_b = encode_local_gcm_payload(**common, salt=salt_b)
        raw_a = base64.b64decode(encoded_a, validate=True)
        raw_b = base64.b64decode(encoded_b, validate=True)

        self.assertNotEqual(key_a, key_b)
        self.assertNotEqual(raw_a[12:-16], raw_b[12:-16])
        self.assertNotEqual(raw_a[-16:], raw_b[-16:])
        with self.assertRaises(InvalidTag):
            AESGCM(key_a).decrypt(common["nonce"], raw_b[12:], b"1700000000")

    def test_empty_payload_has_nonce_and_tag_only(self) -> None:
        encoded = encode_local_gcm_payload(
            seed=bytes(32), salt=bytes(8), nonce=bytes(12),
            unix_seconds=0, payload=b"",
        )
        decoded = base64.b64decode(encoded, validate=True)
        self.assertEqual(len(decoded), 12 + 16)
        self.assertEqual(AESGCM(bytes(32)).decrypt(bytes(12), decoded[12:], b"0"), b"")

    def test_rejects_invalid_input_lengths_and_types(self) -> None:
        valid = {
            "seed": bytes(32), "salt": bytes(8), "nonce": bytes(12),
            "unix_seconds": 0, "payload": b"synthetic",
        }
        for field, bad in (("seed", bytes(31)), ("salt", bytes(7)), ("nonce", bytes(11))):
            with self.subTest(field=field), self.assertRaises(ValueError):
                encode_local_gcm_payload(**(valid | {field: bad}))
        with self.assertRaises(TypeError):
            encode_local_gcm_payload(**(valid | {"payload": bytearray(b"synthetic")}))
        with self.assertRaises(TypeError):
            encode_local_gcm_payload(**(valid | {"payload": "synthetic"}))

        for timestamp in (True, -1, MAX_UNIX_SECONDS + 1, "1700000000"):
            with self.subTest(timestamp_type=type(timestamp).__name__), self.assertRaises(ValueError):
                encode_local_gcm_payload(**(valid | {"unix_seconds": timestamp}))

    def test_sensitive_input_is_not_printed_or_echoed_in_validation_errors(self) -> None:
        secret_sentinel = "synthetic-private-payload-sentinel"
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(TypeError) as caught:
                encode_local_gcm_payload(
                    seed=bytes(32), salt=bytes(8), nonce=bytes(12),
                    unix_seconds=0, payload=secret_sentinel,
                )
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(secret_sentinel, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
