"""Compare a native Authorization value with local Trae/proxy token candidates.

This module is deliberately read-only. It never refreshes, exchanges, or sends a
credential. Candidate strings stay inside a redacted inventory object and are
compared in-process; summaries contain only source labels, booleans, and fixed
reason codes.

For a real local read, callers must opt in by explicitly invoking
``load_candidate_inventory``. The CLI additionally requires ``--live``; its
default mode checks file existence only and does not open either credential file.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trae2api.credential_decrypt import decrypt_value as _trusted_decrypt_value


CLOUD_IDE_JWT_PREFIX = "Cloud-IDE-JWT "
STORAGE_AUTH_KEY = "iCubeAuthInfo://icube.cloudide"
DEFAULT_STORAGE_PATH = (
    Path(os.environ.get("APPDATA", ""))
    / "Trae CN"
    / "User"
    / "globalStorage"
    / "storage.json"
)
DEFAULT_CREDENTIALS_PATH = Path(__file__).resolve().parents[1] / "trae2api" / "trae2api.json"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 128
MAX_JWT_PAYLOAD_BYTES = 64 * 1024
ALLOWED_HEADER_NAMES = frozenset(("authorization", "x-ide-token", "x-cloudide-token"))
ALLOWED_PREFIX_KINDS = frozenset(("none", "cloud_ide_jwt"))


@dataclass(frozen=True)
class CandidateStatus:
    """Safe per-field status; contains no candidate value."""

    source: str
    present: bool
    reason: str
    expired: bool | None = None


@dataclass(frozen=True)
class SourceStatus:
    """Safe source-level status; contains no path or exception text."""

    source: str
    exists: bool | None
    reason: str


@dataclass(frozen=True)
class MatchResult:
    """Safe result for one in-memory header comparison."""

    matched_sources: tuple[str, ...]
    same_value: bool
    cloud_ide_jwt_prefix: bool
    reason: str


@dataclass(frozen=True, repr=False)
class _Candidate:
    source: str
    value: str = field(repr=False)


class CandidateInventory:
    """In-memory token candidates with redacted repr and safe summaries only.

    Use ``match_authorization_value`` in the same process that already owns a
    header value. Do not serialize, log, or send this object or the input value.
    """

    __slots__ = ("source_statuses", "candidate_statuses", "_candidates")

    def __init__(
        self,
        source_statuses: Iterable[SourceStatus],
        candidate_statuses: Iterable[CandidateStatus],
        candidates: Iterable[_Candidate],
    ) -> None:
        self.source_statuses = tuple(source_statuses)
        self.candidate_statuses = tuple(candidate_statuses)
        self._candidates = tuple(candidates)

    def __repr__(self) -> str:
        return "CandidateInventory(<redacted>)"

    def match_authorization_value(self, header_value: object) -> MatchResult:
        """Match a raw Authorization header value without returning its text.

        Normalization removes only the exact, leading ``Cloud-IDE-JWT `` prefix
        from either side. It does not trim whitespace, lowercase, decode, or
        otherwise transform a token. Equality is checked with
        ``hmac.compare_digest`` over the exact UTF-8 encodings.
        """
        normalized_header, has_prefix = _normalize_auth_value(header_value)
        if normalized_header is None:
            return MatchResult((), False, has_prefix, "header_not_string")
        if normalized_header == "":
            return MatchResult((), False, has_prefix, "empty_header_value")

        try:
            header_bytes = normalized_header.encode("utf-8", "strict")
        except UnicodeEncodeError:
            return MatchResult((), False, has_prefix, "invalid_header_text")

        matches: list[str] = []
        for candidate in self._candidates:
            value, _ = _normalize_auth_value(candidate.value)
            if value is None or value == "":
                continue
            try:
                candidate_bytes = value.encode("utf-8", "strict")
            except UnicodeEncodeError:
                continue
            if hmac.compare_digest(header_bytes, candidate_bytes):
                matches.append(candidate.source)

        if matches:
            return MatchResult(tuple(matches), True, has_prefix, "matched")
        return MatchResult((), False, has_prefix, "no_match")

    def match_token_digest(
        self,
        digest_hex: object,
        prefix_kind: object = "none",
        header_name: object = "authorization",
    ) -> MatchResult:
        """Compare a local observer's SHA-256 digest without receiving a token.

        The observer must hash the exact UTF-8 bytes of the token after removing
        at most one exact leading ``Cloud-IDE-JWT `` prefix. It sends only the
        lowercase 64-character SHA-256 hex digest and the fixed header/prefix
        enums. This method never returns or stores the supplied/candidate digest.
        """
        if not isinstance(header_name, str) or header_name not in ALLOWED_HEADER_NAMES:
            return MatchResult((), False, prefix_kind == "cloud_ide_jwt", "invalid_header_name")
        if not isinstance(prefix_kind, str) or prefix_kind not in ALLOWED_PREFIX_KINDS:
            return MatchResult((), False, False, "invalid_prefix_kind")
        if not isinstance(digest_hex, str) or re.fullmatch(r"[0-9a-f]{64}", digest_hex) is None:
            return MatchResult((), False, prefix_kind == "cloud_ide_jwt", "invalid_digest")

        try:
            observed_digest = bytes.fromhex(digest_hex)
        except ValueError:
            return MatchResult((), False, prefix_kind == "cloud_ide_jwt", "invalid_digest")
        if hmac.compare_digest(observed_digest, hashlib.sha256(b"").digest()):
            return MatchResult((), False, prefix_kind == "cloud_ide_jwt", "empty_token_digest")

        matches: list[str] = []
        for candidate in self._candidates:
            value, _ = _normalize_auth_value(candidate.value)
            if value is None or value == "":
                continue
            try:
                candidate_bytes = value.encode("utf-8", "strict")
            except UnicodeEncodeError:
                continue
            candidate_digest = hashlib.sha256(candidate_bytes).digest()
            if hmac.compare_digest(observed_digest, candidate_digest):
                matches.append(candidate.source)

        if matches:
            return MatchResult(tuple(matches), True, prefix_kind == "cloud_ide_jwt", "matched")
        return MatchResult((), False, prefix_kind == "cloud_ide_jwt", "no_match")


@dataclass(frozen=True, repr=False)
class _SelectedValue:
    kind: str
    value: object = field(default=None, repr=False)


class _SelectiveJsonParser:
    """Validate JSON while materializing only explicitly selected values.

    Unselected strings are scanned in-place and never decoded into Python
    strings. This keeps unrelated plaintext credential fields (for example
    refresh tokens or device keys) out of the parsed object graph.
    """

    _NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
    _HEX = frozenset("0123456789abcdefABCDEF")
    _STRING_ESCAPES = frozenset('"\\/bfnrt')

    def __init__(
        self,
        text: str,
        selected_paths: Iterable[tuple[str, ...]],
        value_paths: Iterable[tuple[str, ...]] = (),
    ) -> None:
        self.text = text
        self.length = len(text)
        self.selected_paths = frozenset(selected_paths)
        self.value_paths = frozenset(value_paths)
        self.position = 0
        self.selected: dict[tuple[str, ...], _SelectedValue] = {}

    def parse(self) -> tuple[str, dict[tuple[str, ...], _SelectedValue]]:
        self._skip_ws()
        root_kind = self._parse_value((), 0)
        self._skip_ws()
        if self.position != self.length:
            raise ValueError("invalid_json")
        return root_kind, self.selected

    def _skip_ws(self) -> None:
        text = self.text
        length = self.length
        pos = self.position
        while pos < length and text[pos] in " \t\r\n":
            pos += 1
        self.position = pos

    def _parse_value(self, path: tuple[str, ...], depth: int) -> str:
        if depth > MAX_JSON_DEPTH:
            raise ValueError("json_too_deep")
        self._skip_ws()
        if self.position >= self.length:
            raise ValueError("invalid_json")
        char = self.text[self.position]
        if char == '"':
            value = self._parse_string(capture=path in self.selected_paths)
            kind = "string"
            if path in self.selected_paths:
                self.selected[path] = _SelectedValue(kind, value)
            return kind
        if char == "{":
            if path in self.selected_paths:
                self._clear_selected_descendants(path)
                self.selected[path] = _SelectedValue("object")
            self._parse_object(path, depth + 1)
            return "object"
        if char == "[":
            if path in self.selected_paths:
                self._clear_selected_descendants(path)
                self.selected[path] = _SelectedValue("array")
            self._parse_array(path, depth + 1)
            return "array"
        if char == "t" and self.text.startswith("true", self.position):
            self.position += 4
            kind, value = "boolean", True
        elif char == "f" and self.text.startswith("false", self.position):
            self.position += 5
            kind, value = "boolean", False
        elif char == "n" and self.text.startswith("null", self.position):
            self.position += 4
            kind, value = "null", None
        else:
            match = self._NUMBER.match(self.text, self.position)
            if match is None:
                raise ValueError("invalid_json")
            raw_number = match.group(0)
            self.position = match.end()
            kind = "number"
            value = json.loads(raw_number) if path in self.value_paths else None
        if path in self.selected_paths:
            self.selected[path] = _SelectedValue(kind, value if path in self.value_paths else None)
        return kind

    def _parse_object(self, path: tuple[str, ...], depth: int) -> None:
        self.position += 1  # {
        self._skip_ws()
        if self._consume("}"):
            return
        while True:
            self._skip_ws()
            if self.position >= self.length or self.text[self.position] != '"':
                raise ValueError("invalid_json")
            key = self._parse_string(capture=True)
            self._skip_ws()
            if not self._consume(":"):
                raise ValueError("invalid_json")
            self._parse_value(path + (key,), depth)
            self._skip_ws()
            if self._consume("}"):
                return
            if not self._consume(","):
                raise ValueError("invalid_json")

    def _parse_array(self, path: tuple[str, ...], depth: int) -> None:
        self.position += 1  # [
        self._skip_ws()
        if self._consume("]"):
            return
        index = 0
        while True:
            self._parse_value(path + (f"#{index}",), depth)
            index += 1
            self._skip_ws()
            if self._consume("]"):
                return
            if not self._consume(","):
                raise ValueError("invalid_json")

    def _parse_string(self, capture: bool) -> str | None:
        start = self.position
        self.position += 1  # opening quote
        while self.position < self.length:
            char = self.text[self.position]
            codepoint = ord(char)
            if char == '"':
                self.position += 1
                if capture:
                    return json.loads(self.text[start:self.position])
                return None
            if codepoint < 0x20:
                raise ValueError("invalid_json")
            if char == "\\":
                self.position += 1
                if self.position >= self.length:
                    raise ValueError("invalid_json")
                escaped = self.text[self.position]
                if escaped == "u":
                    end = self.position + 5
                    if end > self.length or any(c not in self._HEX for c in self.text[self.position + 1:end]):
                        raise ValueError("invalid_json")
                    self.position = end
                    continue
                if escaped not in self._STRING_ESCAPES:
                    raise ValueError("invalid_json")
            self.position += 1
        raise ValueError("invalid_json")

    def _consume(self, expected: str) -> bool:
        if self.position < self.length and self.text[self.position] == expected:
            self.position += 1
            return True
        return False

    def _clear_selected_descendants(self, path: tuple[str, ...]) -> None:
        for selected_path in tuple(self.selected):
            if len(selected_path) > len(path) and selected_path[:len(path)] == path:
                del self.selected[selected_path]


def _normalize_auth_value(value: object) -> tuple[str | None, bool]:
    if not isinstance(value, str):
        return None, False
    if value.startswith(CLOUD_IDE_JWT_PREFIX):
        return value[len(CLOUD_IDE_JWT_PREFIX):], True
    return value, False


def _token_expired_claim(value: str, now: float) -> bool | None:
    normalized, _ = _normalize_auth_value(value)
    if not normalized:
        return None
    parts = normalized.split(".")
    if len(parts) != 3 or not parts[1] or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[1]):
        return None
    try:
        payload_bytes = base64.b64decode(
            parts[1] + "=" * (-len(parts[1]) % 4), altchars=b"-_", validate=True
        )
        if len(payload_bytes) > MAX_JWT_PAYLOAD_BYTES:
            return None
        payload_text = payload_bytes.decode("utf-8", "strict")
        root_kind, selected = _SelectiveJsonParser(
            payload_text,
            selected_paths=(("exp",),),
            value_paths=(("exp",),),
        ).parse()
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if root_kind != "object":
        return None
    exp = selected.get(("exp",))
    if exp is None or exp.kind != "number" or isinstance(exp.value, bool):
        return None
    try:
        timestamp = float(exp.value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(timestamp):
        return None
    return now >= timestamp


def _read_limited_text(path: Path) -> tuple[str | None, str, bool | None]:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
    except FileNotFoundError:
        return None, "missing_file", False
    except IsADirectoryError:
        return None, "not_a_file", True
    except OSError:
        return None, "unreadable", None
    if len(data) > MAX_SOURCE_BYTES:
        return None, "too_large", True
    try:
        return data.decode("utf-8", "strict"), "read", True
    except UnicodeDecodeError:
        return None, "invalid_encoding", True


def _parse_selected_json(
    text: str,
    paths: Iterable[tuple[str, ...]],
    value_paths: Iterable[tuple[str, ...]] = (),
) -> tuple[str, dict[tuple[str, ...], _SelectedValue]]:
    return _SelectiveJsonParser(text, paths, value_paths).parse()


def _status_for_value(source: str, selected: _SelectedValue | None, now: float) -> tuple[CandidateStatus, _Candidate | None]:
    if selected is None:
        return CandidateStatus(source, False, "missing_field", None), None
    if selected.kind != "string":
        return CandidateStatus(source, False, "wrong_type", None), None
    value = selected.value
    if not isinstance(value, str):
        return CandidateStatus(source, False, "wrong_type", None), None
    normalized, _ = _normalize_auth_value(value)
    if value == "" or normalized == "":
        reason = "empty_after_auth_prefix" if value else "empty_value"
        return CandidateStatus(source, False, reason, None), None
    candidate = _Candidate(source, value)
    return CandidateStatus(source, True, "available", _token_expired_claim(value, now)), candidate


def _failed_candidate_status(source: str, reason: str) -> CandidateStatus:
    return CandidateStatus(source, False, reason, None)


def _storage_candidates(
    path: Path,
    decrypt_value: Callable[[str], str | None],
    now: float,
) -> tuple[SourceStatus, CandidateStatus, _Candidate | None]:
    label = "trae.storage.token"
    text, read_reason, exists = _read_limited_text(path)
    if text is None:
        return SourceStatus("trae_storage", exists, read_reason), _failed_candidate_status(label, read_reason), None
    try:
        root_kind, selected = _parse_selected_json(text, ((STORAGE_AUTH_KEY,),))
    except (ValueError, json.JSONDecodeError):
        reason = "invalid_json"
        return SourceStatus("trae_storage", exists, reason), _failed_candidate_status(label, reason), None
    if root_kind != "object":
        reason = "invalid_root_type"
        return SourceStatus("trae_storage", exists, reason), _failed_candidate_status(label, reason), None
    encrypted = selected.get((STORAGE_AUTH_KEY,))
    if encrypted is None:
        reason = "auth_record_missing"
        return SourceStatus("trae_storage", exists, reason), _failed_candidate_status(label, reason), None
    if encrypted.kind != "string" or not isinstance(encrypted.value, str):
        reason = "encrypted_auth_wrong_type"
        return SourceStatus("trae_storage", exists, reason), _failed_candidate_status(label, reason), None
    try:
        auth_plain = decrypt_value(encrypted.value)
    except Exception:
        reason = "decrypt_failed"
        return SourceStatus("trae_storage", exists, reason), _failed_candidate_status(label, reason), None
    if not isinstance(auth_plain, str) or auth_plain == "":
        reason = "decrypt_failed"
        return SourceStatus("trae_storage", exists, reason), _failed_candidate_status(label, reason), None
    try:
        auth_kind, auth_selected = _parse_selected_json(auth_plain, (("token",),))
    except (ValueError, json.JSONDecodeError):
        reason = "decrypted_auth_invalid_json"
        return SourceStatus("trae_storage", exists, reason), _failed_candidate_status(label, reason), None
    if auth_kind != "object":
        reason = "decrypted_auth_invalid_root_type"
        return SourceStatus("trae_storage", exists, reason), _failed_candidate_status(label, reason), None
    status, candidate = _status_for_value(label, auth_selected.get(("token",)), now)
    reason = "ready" if status.reason in ("available", "missing_field", "wrong_type", "empty_value", "empty_after_auth_prefix") else status.reason
    return SourceStatus("trae_storage", exists, reason), status, candidate


def _proxy_candidates(path: Path, now: float) -> tuple[SourceStatus, tuple[CandidateStatus, CandidateStatus], tuple[_Candidate, ...]]:
    token_label, jwt_label = "proxy.token", "proxy.jwt"
    text, read_reason, exists = _read_limited_text(path)
    if text is None:
        statuses = (_failed_candidate_status(token_label, read_reason), _failed_candidate_status(jwt_label, read_reason))
        return SourceStatus("proxy_credentials", exists, read_reason), statuses, ()
    paths = (("auth",), ("auth", "token"), ("auth", "jwt"), ("token",), ("jwt",))
    try:
        root_kind, selected = _parse_selected_json(text, paths)
    except (ValueError, json.JSONDecodeError):
        reason = "invalid_json"
        statuses = (_failed_candidate_status(token_label, reason), _failed_candidate_status(jwt_label, reason))
        return SourceStatus("proxy_credentials", exists, reason), statuses, ()
    if root_kind != "object":
        reason = "invalid_root_type"
        statuses = (_failed_candidate_status(token_label, reason), _failed_candidate_status(jwt_label, reason))
        return SourceStatus("proxy_credentials", exists, reason), statuses, ()

    auth_section = selected.get(("auth",))
    if auth_section is not None:
        if auth_section.kind != "object":
            reason = "auth_section_wrong_type"
            statuses = (_failed_candidate_status(token_label, reason), _failed_candidate_status(jwt_label, reason))
            return SourceStatus("proxy_credentials", exists, reason), statuses, ()
        token_value = selected.get(("auth", "token"))
        jwt_value = selected.get(("auth", "jwt"))
    else:
        token_value = selected.get(("token",))
        jwt_value = selected.get(("jwt",))

    token_status, token_candidate = _status_for_value(token_label, token_value, now)
    jwt_status, jwt_candidate = _status_for_value(jwt_label, jwt_value, now)
    candidates = tuple(candidate for candidate in (token_candidate, jwt_candidate) if candidate is not None)
    return SourceStatus("proxy_credentials", exists, "ready"), (token_status, jwt_status), candidates


def load_candidate_inventory(
    storage_path: str | os.PathLike[str] | None = None,
    credentials_path: str | os.PathLike[str] | None = None,
    *,
    decrypt_value: Callable[[str], str | None] = _trusted_decrypt_value,
    now: float | None = None,
) -> CandidateInventory:
    """Read only local candidate token fields and return a redacted matcher.

    The Trae storage record is decrypted with the existing trusted
    ``credential_decrypt.decrypt_value`` function. Only its ``token`` field is
    selected. Proxy credentials may be nested under ``auth`` or at the root;
    only ``token`` and ``jwt`` are selected. Refresh tokens, device/private
    keys, user identifiers, and chat data are never selected or returned.

    This function performs local file reads only. It does not import or invoke
    ``TraeAuth``, ``get_jwt``, OAuth, HTTP, refresh, or rotation code.
    """
    storage = Path(storage_path) if storage_path is not None else DEFAULT_STORAGE_PATH
    credentials = Path(credentials_path) if credentials_path is not None else DEFAULT_CREDENTIALS_PATH
    at_time = time.time() if now is None else float(now)
    storage_source, storage_status, storage_candidate = _storage_candidates(storage, decrypt_value, at_time)
    proxy_source, proxy_statuses, proxy_candidates = _proxy_candidates(credentials, at_time)
    candidates = ([storage_candidate] if storage_candidate is not None else []) + list(proxy_candidates)
    return CandidateInventory(
        (storage_source, proxy_source),
        (storage_status, *proxy_statuses),
        candidates,
    )


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - covered via CLI test
        raise ValueError("invalid_arguments")


def _file_exists(path: Path) -> bool | None:
    try:
        return path.is_file()
    except OSError:
        return None


def _inventory_report(inventory: CandidateInventory) -> dict[str, object]:
    return {
        "mode": "live_read",
        "live_read": True,
        "sources": {
            item.source: {"exists": item.exists, "reason": item.reason}
            for item in inventory.source_statuses
        },
        "candidates": {
            item.source: {"present": item.present, "reason": item.reason, "expired": item.expired}
            for item in inventory.candidate_statuses
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(add_help=True, prog="native_auth_matcher")
    parser.add_argument("--live", action="store_true", help="explicitly read local token candidates")
    parser.add_argument("--storage-path", help="Trae CN storage.json path")
    parser.add_argument("--credentials-path", help="proxy credentials JSON path")
    try:
        args = parser.parse_args(argv)
        storage = Path(args.storage_path) if args.storage_path else DEFAULT_STORAGE_PATH
        credentials = Path(args.credentials_path) if args.credentials_path else DEFAULT_CREDENTIALS_PATH
        if args.live:
            report = _inventory_report(load_candidate_inventory(storage, credentials))
        else:
            report = {
                "mode": "safe_preview",
                "live_read": False,
                "reason": "live_mode_required",
                "sources": {
                    "trae_storage": {"exists": _file_exists(storage), "reason": "not_read"},
                    "proxy_credentials": {"exists": _file_exists(credentials), "reason": "not_read"},
                },
            }
        print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
        return 0
    except ValueError:
        print(json.dumps({"mode": "error", "reason": "invalid_arguments"}, separators=(",", ":")))
        return 2
    except Exception:
        # Fixed fallback: never echo exception text, paths, or file contents.
        print(json.dumps({"mode": "error", "reason": "internal_error"}, separators=(",", ":")))
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised in subprocess tests
    raise SystemExit(main())
