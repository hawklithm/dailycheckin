"""Persistent lab-only P-256 keys and domain-separated signatures."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import re
import uuid

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .storage import atomic_json, canonical, confined, read_json


def public_key(pem: str):
    if not isinstance(pem, str) or len(pem) > 2048:
        raise ValueError("invalid lab public key")
    try:
        key = serialization.load_pem_public_key(pem.encode())
    except (ValueError, TypeError, UnicodeError, UnsupportedAlgorithm):
        raise ValueError("invalid lab public key") from None
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("lab key must be P-256")
    return key


def key_id(pem: str) -> str:
    key = public_key(pem)
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return "lab-key-" + hashlib.sha256(der).hexdigest()


def signing_bytes(path: str, payload: dict) -> bytes:
    return ("local-device-lab-proof-v1\nPOST\n" + path + "\n" + canonical(payload)).encode()


def verify(pem: str, path: str, payload: dict, signature: str) -> bool:
    try:
        if not isinstance(signature, str) or len(signature) > 256:
            return False
        public_key(pem).verify(base64.b64decode(signature, validate=True), signing_bytes(path, payload), ec.ECDSA(hashes.SHA256()))
        return True
    except (ValueError, TypeError, InvalidSignature, UnicodeError, UnsupportedAlgorithm):
        return False


def _names(physical: str, installation: str) -> None:
    if physical not in ("lab-physical-h1", "lab-physical-h2") or installation not in ("I1", "I2"):
        raise ValueError("unknown synthetic installation")


def _path(directory: Path, physical: str, installation: str) -> Path:
    _names(physical, installation)
    return confined(directory / f"{physical}-{installation}.installation.json")


def _secret_path(directory: Path, metadata: dict) -> Path:
    digest = metadata["key_id"].removeprefix("lab-key-")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid persisted key ID")
    return confined(directory / f"{metadata['physical_key']}-{metadata['installation_id']}-{digest}.p256.secret")


def _private(directory: Path, metadata: dict):
    value = read_json(_secret_path(directory, metadata))
    try:
        if set(value) != {"schema_version", "private_key_pem"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError()
        key = serialization.load_pem_private_key(value["private_key_pem"].encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        if key_id(pem) != metadata["key_id"] or pem != metadata["public_key_pem"]:
            raise ValueError()
        return key
    except (ValueError, TypeError, AttributeError, KeyError, UnsupportedAlgorithm):
        raise ValueError("persisted lab key does not match installation") from None


def _validate(metadata: dict, physical: str, installation: str, *, legacy: bool = False) -> None:
    fields = {"schema_version", "synthetic", "physical_key", "installation_id", "machine_id", "key_label", "key_kind"}
    if not legacy:
        fields |= {"public_key_pem", "key_id"}
    if (set(metadata) != fields or type(metadata.get("schema_version")) is not int
            or metadata["schema_version"] != (1 if legacy else 2) or metadata.get("synthetic") is not True
            or metadata.get("physical_key") != physical or metadata.get("installation_id") != installation
            or metadata.get("key_kind") != ("synthetic_label_no_signature" if legacy else "ecdsa_p256")
            or not isinstance(metadata.get("machine_id"), str)
            or not re.fullmatch(r"lab-machine-[0-9a-f]{32}", metadata["machine_id"])
            or not isinstance(metadata.get("key_label"), str)
            or not re.fullmatch(r"lab-key-label-[0-9a-f]{32}", metadata["key_label"])):
        raise ValueError("invalid persisted lab installation")
    if not legacy and key_id(metadata["public_key_pem"]) != metadata["key_id"]:
        raise ValueError("persisted lab public key mismatch")


def _create(directory: Path, physical: str, installation: str, legacy: dict | None = None) -> dict:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    metadata = {"schema_version": 2, "synthetic": True, "physical_key": physical, "installation_id": installation,
                "machine_id": legacy["machine_id"] if legacy else "lab-machine-" + uuid.uuid4().hex,
                "key_label": legacy["key_label"] if legacy else "lab-key-label-" + uuid.uuid4().hex,
                "key_kind": "ecdsa_p256", "public_key_pem": public, "key_id": key_id(public)}
    secret = {"schema_version": 1, "private_key_pem": key.private_bytes(serialization.Encoding.PEM,
              serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()}
    # Immutable versioned secret first; atomically publish its public metadata
    # last. Rebuild failures cannot break the old metadata/key pairing.
    atomic_json(_secret_path(directory, metadata), secret, create_only=True)
    return metadata


def installation(directory: Path, physical: str, installation_id: str, *, rebuild: bool = False) -> dict:
    path = _path(directory, physical, installation_id)
    current = read_json(path) if path.exists() else None
    legacy = current is not None and type(current.get("schema_version")) is int and current["schema_version"] == 1
    if current is not None:
        _validate(current, physical, installation_id, legacy=legacy)
        if not legacy:
            _private(directory, current)
            if not rebuild:
                return current
        atomic_json(directory / "history" / f"{physical}-{installation_id}-{uuid.uuid4().hex}.json", current, create_only=True)
    metadata = _create(directory, physical, installation_id, current if legacy and not rebuild else None)
    atomic_json(path, metadata, create_only=current is None)
    winner = read_json(path)
    _validate(winner, physical, installation_id)
    _private(directory, winner)
    return winner


def sign(directory: Path, metadata: dict, path: str, payload: dict) -> str:
    _names(metadata["physical_key"], metadata["installation_id"])
    _validate(metadata, metadata["physical_key"], metadata["installation_id"])
    signature = _private(directory, metadata).sign(signing_bytes(path, payload), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode()
