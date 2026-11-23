"""Parameterized local AES-GCM byte transform from the static native trace.

This module only derives the local 32-byte AES key input, encrypts caller-
provided bytes with caller-provided nonce and Unix seconds, and encodes
``nonce || ciphertext || tag`` as padded standard Base64. It does not generate
inputs, construct a request/header, or contact a service.
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SEED_BYTES = 32
SALT_BYTES = 8
NONCE_BYTES = 12
TAG_BYTES = 16
MAX_UNIX_SECONDS = (1 << 64) - 1


def _require_bytes(name: str, value: object, expected_length: int | None = None) -> bytes:
    if type(value) is not bytes:
        raise TypeError(f"{name} must be bytes")
    if expected_length is not None and len(value) != expected_length:
        raise ValueError(f"{name} must be exactly {expected_length} bytes")
    return value


def derive_local_aes256_key(seed: bytes, salt: bytes) -> bytes:
    """XOR an explicit 8-byte salt into seed bytes 0..7; copy bytes 8..31."""
    seed = _require_bytes("seed", seed, SEED_BYTES)
    salt = _require_bytes("salt", salt, SALT_BYTES)
    result = bytearray(seed)
    for index, salt_byte in enumerate(salt):
        result[index] ^= salt_byte
    return bytes(result)


def encode_local_gcm_payload(
    *,
    seed: bytes,
    salt: bytes,
    nonce: bytes,
    unix_seconds: int,
    payload: bytes,
) -> bytes:
    """Return padded Base64 of ``nonce || AES-256-GCM(payload) || tag``.

    The AAD is the decimal ASCII representation of ``unix_seconds``. All
    inputs are explicit so callers control the seed, salt, nonce, timestamp,
    and payload. The result is a local primitive output, not a complete
    ``X-Request-Pin`` value or request header.
    """
    seed = _require_bytes("seed", seed, SEED_BYTES)
    salt = _require_bytes("salt", salt, SALT_BYTES)
    nonce = _require_bytes("nonce", nonce, NONCE_BYTES)
    payload = _require_bytes("payload", payload)
    if (not isinstance(unix_seconds, int) or isinstance(unix_seconds, bool) or
            not 0 <= unix_seconds <= MAX_UNIX_SECONDS):
        raise ValueError("unix_seconds must be an unsigned 64-bit integer")

    key = derive_local_aes256_key(seed, salt)
    aad = str(unix_seconds).encode("ascii")
    ciphertext_and_tag = AESGCM(key).encrypt(nonce, payload, aad)
    if len(ciphertext_and_tag) != len(payload) + TAG_BYTES:
        raise RuntimeError("unexpected AES-GCM output length")
    return base64.b64encode(nonce + ciphertext_and_tag)
