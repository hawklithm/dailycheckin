"""Read the installed client's non-authentication request configuration.

Mirrors the reviewed session header rules. Never creates native identity files,
reads a token, or performs device registration/network requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from urllib.parse import urlsplit

from buddy_agent_auth.providers.trae.client_metadata import installed_client


def _read_jsonc(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    # Preserve quoted URLs and escaped quotes while removing JSONC comments.
    text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/',
                  lambda m: m[0] if m[0].startswith('"') else " ", text)
    text = re.sub(r'("(?:\\.|[^"\\])*")|,\s*(?=[}\]])',
                  lambda m: m[1] or "", text)
    try:
        value = json.loads(text)
    except ValueError:
        raise ValueError("invalid Trae JSON/JSONC configuration") from None
    if not isinstance(value, dict):
        raise ValueError("Trae configuration must be a JSON object")
    return value


def _stored_string(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else value
    except ValueError:
        return value


def _machine_headers(directory: Path) -> dict[str, str]:
    # Match hRe: application storage first, then the existing machineid file.
    # Unlike native initialization, this reader does not generate/persist an ID.
    values = {}
    database = directory / "User/globalStorage/state.vscdb"
    if database.exists():
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                values = dict(connection.execute(
                    "SELECT key,value FROM ItemTable WHERE key IN (?,?)",
                    ("storage.serviceMachineId", "telemetry.machineId")))
        except sqlite3.Error:
            pass  # The machineid file is the native fallback as well.
    service_id = _stored_string(values.get("storage.serviceMachineId"))
    if not service_id:
        try:
            candidate = (directory / "machineid").read_text(encoding="utf-8").strip()
            uuid.UUID(candidate)
            service_id = candidate
        except (OSError, ValueError):
            pass
    if not service_id:
        return {}
    session_id = _stored_string(values.get("telemetry.machineId"))
    if not session_id:
        storage = _read_jsonc(directory / "User/globalStorage/storage.json")
        session_id = storage.get("telemetry.machineId")
    return {"X-Market-User-Id": service_id,
            "VSCode-SessionId": session_id if isinstance(session_id, str) and session_id else service_id}


def validate_base_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("check-in base URL must be an HTTPS origin")
    return value.rstrip("/")


@dataclass(frozen=True)
class CheckinProfile:
    editor_version: str
    client_name: str
    base_url: str
    headers: tuple[tuple[str, str], ...]

    @classmethod
    def load(cls) -> "CheckinProfile":
        product = installed_client()
        location = os.environ.get("TRAE2API_USER_DATA")
        if not location and os.environ.get("APPDATA"):
            location = str(Path(os.environ["APPDATA"]) / "Trae CN")
        directory = Path(location) if location else None
        settings = _read_jsonc(directory / "User/settings.json") if directory else {}
        headers = {}
        env, lane = settings.get("ai_assistant.request.env"), settings.get("ai_assistant.request.ppe")
        # fRe (marketplace rule) runs after the authentication rule and mirrors
        # its environment headers; the wrapper additionally supports envLane.
        if isinstance(env, str) and env and isinstance(lane, str) and lane:
            headers.update({f"x-use-{env}": "1", "x-tt-env": lane})
        elif env == "boe":
            headers.update({"x-use-boe": "1", "x-tt-env": lane if isinstance(lane, str) else ""})
        env_lane = settings.get("ai_assistant.request.envLane")
        if isinstance(env_lane, str) and env_lane:
            headers["x-env-lane"] = env_lane
        telemetry_all = (settings.get("telemetry.telemetryLevel", "all") == "all"
                         and settings.get("telemetry.enableTelemetry") is not False
                         and settings.get("telemetry.enableCrashReporter") is not False)
        if directory and product.telemetry_enabled and telemetry_all:
            headers.update(_machine_headers(directory))
        return cls(product.editor_version, product.name, validate_base_url(product.ug_url),
                   tuple(headers.items()))
