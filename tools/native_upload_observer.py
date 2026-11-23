"""Fail-closed Python driver for a separately reviewed Cronet upload observer.

This driver records only bounded schema projections and safe metadata. A private
Frida message carries a short-lived SHA-256 of a typed auth header value; that
message is consumed in memory and never passed through the JSONL sanitizer.
Raw auth values and request bodies are never written by this driver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
AGENT_PATH = TOOLS / "native_upload_observer.js"
CORE_PATH = TOOLS / "native_upload_projection_core.js"
OUTPUT_BASE = ROOT / "logs" / "native_upload_observer_20261027"
EXPECTED_PYTHON = Path(r"E:\tools\frida\venv\Scripts\python.exe")

DEFAULT_PID = 144016
DEFAULT_PARENT_PID = 251084
DEFAULT_CREATED = "2026-10-27T09:33:35.107913+08:00"
DEFAULT_IMAGE_PATH = Path(r"D:\Users\marcus\AppData\Local\Programs\Trae CN\Trae CN.exe")
DEFAULT_IMAGE_SHA256 = "6069AC7FB5D1E20FA08A1635CA4613957EB81F9DD670DCA5CBA844CAC1062CA4"
DEFAULT_MODULE_PATH = Path(r"D:\Users\marcus\AppData\Local\Programs\Trae CN\sscronet.dll")
DEFAULT_MODULE_SHA256 = "288F987E64107A603CAE0E04D3282935B4017DC1C042EA579334DA49984FB79A"
DEFAULT_PROCESS_TYPE = "utility"
DEFAULT_UTILITY_SUBTYPE = "network.mojom.NetworkService"
INSTALL_ROOT = DEFAULT_IMAGE_PATH.parent

ROUTES = {
    "/api/agent/v3/create_agent_task": {
        "route_name": "create_agent_task",
        "path_sha256": "e83038e8075b1149396727c1454bcb882d3267826c9e114ad312969596616d88",
    },
    "/api/agent/v3/llm_utils_chat": {
        "route_name": "llm_utils_chat",
        "path_sha256": "ac4781f6c4434a5142b97824be620dc13b6d020747bc32147732bdf487b1f28d",
    },
    "/api/agent/v3/workflow/start": {
        "route_name": "workflow_start",
        "path_sha256": "9edde739e9e152abec7cbc6fbc1e9518ccde70c3346e2a12df09322fe3513078",
    },
}
KNOWN_CALLBACK_MODULES = {"trae cn.exe", "sscronet.dll", "aha_net.dll", "ttnetdownloader.dll"}
EXPECTED_FIXED_MODULE_HASHES = {
    "trae cn.exe": DEFAULT_IMAGE_SHA256,
    "sscronet.dll": DEFAULT_MODULE_SHA256,
    "aha_net.dll": "CF38F525CDA10304BED392D7FEF8041BEB0C0DC445BF3B980164FD2D5DA43C02",
}
ALLOWED_CALLBACK_ROLES = {"get_length", "read", "rewind", "close"}
ALLOWED_AUTH_HEADERS = {"authorization", "x-ide-token", "x-cloudide-token"}
ALLOWED_PREFIX_KINDS = {"none", "cloud_ide_jwt"}
ALLOWED_AUTH_SOURCES = {"trae.storage.token", "proxy.token", "proxy.jwt"}
ALLOWED_AUTH_REASONS = {
    "matched", "no_match", "empty_token_digest", "invalid_digest",
    "invalid_header_name", "invalid_prefix_kind", "matcher_unavailable",
    "auth_matching_disabled", "matcher_error",
}
ALLOWED_PARSE_STATES = {"json", "invalid_json", "invalid_utf8", "bounded_unknown", "invalid_buffer"}
ALLOWED_VALUE_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null", "unknown"}
ALLOWED_VALUE_STATES = {"target", "other"}
ALLOWED_SAFE_ENUMS = {
    "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra",
    "auto", "default", "manual", "enabled", "disabled", "on", "off",
    "balanced", "fast", "quality",
}
# These finite sets constrain projection output. They do not establish that a
# particular value appeared in this capture or is the active wire protocol.
ALLOWED_ENUM_VALUES_BY_KEY = {
    "model_selection_strategy": ALLOWED_SAFE_ENUMS,
    "reasoning_effort": ALLOWED_SAFE_ENUMS,
    "reasoning_mode": ALLOWED_SAFE_ENUMS,
    "strategy": ALLOWED_SAFE_ENUMS,
    "function": {
        "chat", "builder", "agent", "code", "completion", "solo", "plan", "edit",
        "inline_chat", "reader", "custom", "assistant", "chat_builder", "agent_builder",
        "solo_builder", "solo_coding", "fast_apply", "commit_message", "summary",
        "terminal", "solo_agent",
    },
    "agent_type": {"chat", "builder", "solo_agent"},
    "scene_location": {1, 2},
}
SAFE_PATH_KEYS = {
    "agent", "agent_id", "agent_task_id", "agent_type", "arguments", "body",
    "chat_history", "chat_session_id", "client_info", "common_params", "content",
    "content_blocks", "conversation_id", "custom_model", "custom_params", "data",
    "assistant", "developer", "display_model_name", "done", "error", "error_code", "event",
    "extra_chat_params", "function", "function_call", "function_name", "function_response",
    "id", "input", "input_tokens", "is_streaming", "items", "message", "message_id",
    "message_contents", "messages", "metadata", "model", "model_config", "model_config_name", "model_name",
    "model_selection_strategy", "name", "operation_id", "output", "output_tokens",
    "params", "parsed_query", "payload", "prompt", "prompt_tokens", "query",
    "reasoning_content", "reasoning_effort", "reasoning_mode", "request", "request_id",
    "response", "result", "role", "scheduled_task_context", "session_id", "status",
    "stream", "task_id", "text", "text_content", "timestamp", "timing_events",
    "token_usage", "total_tokens", "trace_id", "type", "usage", "user_input",
    "user_message_id", "user_info", "workflow", "workflow_id", "value",
    "cache_read_tokens", "cache_creation_tokens", "cached_tokens", "completion_tokens",
    "context_usage", "final_chunk", "tool", "tool_calls", "tool_choice", "tools",
    "choices", "delta", "finish_reason", "custom_model_config", "custom_model_name",
    "strategy", "scene_location", "agent_config", "system", "user", "x",
}
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
MODULE_HASH_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
HEADER_RE = re.compile(r"[a-z0-9-]{1,64}\Z")
MAX_SECONDS = 300
MAX_EVENTS = 256
MAX_OUTPUT_BYTES = 256 * 1024
MAX_RESERVED_BYTES = 8192
MAX_LINE_BYTES = 128 * 1024
MAX_SCHEMA = 128
MAX_PATH_SEGMENTS = 16
MAX_MARKER_PATHS = 16
MAX_ID_FIELDS = 32
MAX_MODEL_FIELDS = 24
MAX_USAGE_FIELDS = 32
MAX_CALLBACK_MODULES = 8
MAX_PENDING_AUTH_DIGESTS = 128
MAX_PROJECTION_REJECTION_DIAGNOSTICS = 48
PROJECTION_REJECTION_STAGES = {
    "event_shape", "event_bounds", "route_identity", "projection_shape",
    "parse_state", "body_bytes", "marker", "marker_paths", "non_json_shape",
    "json_shape", "schema", "model", "enum", "path", "id_hash", "usage",
    "sequence", "line_limit", "output_limit",
}

# Importing the reviewed metadata driver only provides the already-audited
# process identity and timestamp helpers; it does not attach or read files.
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import native_metadata_observer as metadata_driver  # noqa: E402


def _path_key(path: str | Path) -> str:
    return str(path).replace("/", "\\").casefold()


def _safe_path_segment(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    if kind == "key":
        name = value.get("value")
        if not isinstance(name, str) or name not in SAFE_PATH_KEYS:
            return None
        return {"kind": "key", "value": name}
    if kind == "hash":
        digest = value.get("sha256")
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            return None
        return {"kind": "hash", "sha256": digest}
    if kind in {"array_item", "embedded_json"}:
        return {"kind": kind}
    return None


def _safe_path(value: object) -> list[dict] | None:
    if not isinstance(value, list) or len(value) > MAX_PATH_SEGMENTS:
        return None
    result = []
    for item in value:
        segment = _safe_path_segment(item)
        if segment is None:
            return None
        result.append(segment)
    return result


def _sanitize_projection(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    base_fields = {"parse_state", "body_bytes", "marker_hit", "marker_semantics", "marker_paths"}
    projection_fields = base_fields | {"schema", "model_fields", "enum_fields", "id_hashes", "usage"}
    if set(value) - projection_fields or not base_fields.issubset(value):
        return None
    parse_state = value.get("parse_state")
    body_bytes = value.get("body_bytes")
    marker_hit = value.get("marker_hit")
    marker_semantics = value.get("marker_semantics")
    if parse_state not in ALLOWED_PARSE_STATES:
        return None
    if not isinstance(body_bytes, int) or isinstance(body_bytes, bool) or not 0 <= body_bytes <= 1024 * 1024:
        return None
    if not isinstance(marker_hit, bool) or marker_semantics != "unverified":
        return None
    marker_paths = value.get("marker_paths")
    if not isinstance(marker_paths, list) or len(marker_paths) > MAX_MARKER_PATHS:
        return None
    safe_marker_paths = []
    for item in marker_paths:
        path = _safe_path(item)
        if path is None:
            return None
        safe_marker_paths.append(path)
    if marker_hit != bool(safe_marker_paths):
        return None

    # The JS core intentionally returns only the five base fields for an
    # invalid or over-bounded payload. Treat that as a safe non-JSON summary;
    # do not reject an otherwise valid route event just because there is no
    # schema to project.
    if parse_state != "json":
        if set(value) != base_fields or marker_hit or safe_marker_paths:
            return None
        return {
            "parse_state": parse_state, "body_bytes": body_bytes,
            "marker_hit": False, "marker_semantics": "unverified",
            "marker_paths": [], "schema": [], "model_fields": [],
            "enum_fields": [], "id_hashes": [], "usage": [],
        }
    if set(value) != projection_fields:
        return None

    schema = value.get("schema")
    if not isinstance(schema, list) or len(schema) > MAX_SCHEMA:
        return None
    safe_schema = []
    for item in schema:
        if not isinstance(item, dict) or set(item) != {"path", "type", "top_level"}:
            return None
        path = _safe_path(item.get("path"))
        if not path or item.get("type") not in ALLOWED_VALUE_TYPES or not isinstance(item.get("top_level"), bool):
            return None
        safe_schema.append({"path": path, "type": item["type"], "top_level": item["top_level"]})

    model_fields = value.get("model_fields")
    if not isinstance(model_fields, list) or len(model_fields) > MAX_MODEL_FIELDS:
        return None
    safe_models = []
    for item in model_fields:
        if not isinstance(item, dict) or set(item) != {"path", "value_state"}:
            return None
        path = _safe_path(item.get("path"))
        if not path or item.get("value_state") not in ALLOWED_VALUE_STATES:
            return None
        safe_models.append({"path": path, "value_state": item["value_state"]})

    enum_fields = value.get("enum_fields")
    if not isinstance(enum_fields, list) or len(enum_fields) > MAX_MODEL_FIELDS:
        return None
    safe_enums = []
    for item in enum_fields:
        if not isinstance(item, dict) or set(item) != {"path", "value"}:
            return None
        path = _safe_path(item.get("path"))
        enum_value = item.get("value")
        enum_key = path[-1].get("value") if path and path[-1].get("kind") == "key" else None
        allowed_values = ALLOWED_ENUM_VALUES_BY_KEY.get(enum_key)
        if not path or allowed_values is None:
            return None
        if enum_key == "scene_location":
            if not isinstance(enum_value, int) or isinstance(enum_value, bool) or enum_value not in allowed_values:
                return None
        elif not isinstance(enum_value, str) or enum_value not in allowed_values:
            return None
        safe_enums.append({"path": path, "value": enum_value})

    id_hashes = value.get("id_hashes")
    if not isinstance(id_hashes, list) or len(id_hashes) > MAX_ID_FIELDS:
        return None
    safe_ids = []
    for item in id_hashes:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            return None
        path = _safe_path(item.get("path"))
        digest = item.get("sha256")
        if not path or not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            return None
        safe_ids.append({"path": path, "sha256": digest})

    usage = value.get("usage")
    if not isinstance(usage, list) or len(usage) > MAX_USAGE_FIELDS:
        return None
    safe_usage = []
    for item in usage:
        if not isinstance(item, dict) or set(item) != {"path", "value"}:
            return None
        path, number = _safe_path(item.get("path")), item.get("value")
        if not path or not isinstance(number, int) or isinstance(number, bool) or not 0 <= number <= 1_000_000_000:
            return None
        safe_usage.append({"path": path, "value": number})

    return {
        "parse_state": parse_state, "body_bytes": body_bytes,
        "marker_hit": marker_hit, "marker_semantics": "unverified",
        "marker_paths": safe_marker_paths, "schema": safe_schema,
        "model_fields": safe_models, "enum_fields": safe_enums,
        "id_hashes": safe_ids, "usage": safe_usage,
    }


def _projection_rejection_stage(value: object) -> str:
    """Classify a rejected projection with fixed labels only."""
    if not isinstance(value, dict):
        return "projection_shape"
    base = {"parse_state", "body_bytes", "marker_hit", "marker_semantics", "marker_paths"}
    full = base | {"schema", "model_fields", "enum_fields", "id_hashes", "usage"}
    if set(value) - full or not base.issubset(value):
        return "projection_shape"
    state = value.get("parse_state")
    if state not in ALLOWED_PARSE_STATES:
        return "parse_state"
    body_bytes = value.get("body_bytes")
    if not isinstance(body_bytes, int) or isinstance(body_bytes, bool) or not 0 <= body_bytes <= 1024 * 1024:
        return "body_bytes"
    marker_hit = value.get("marker_hit")
    if not isinstance(marker_hit, bool) or value.get("marker_semantics") != "unverified":
        return "marker"
    marker_paths = value.get("marker_paths")
    if not isinstance(marker_paths, list) or len(marker_paths) > MAX_MARKER_PATHS:
        return "marker_paths"
    if any(_safe_path(path) is None for path in marker_paths):
        return "path"
    if marker_hit != bool(marker_paths):
        return "marker"
    if state != "json":
        if set(value) != base:
            return "non_json_shape"
        return "projection_format"
    if set(value) != full:
        return "json_shape"

    schema = value.get("schema")
    if not isinstance(schema, list) or len(schema) > MAX_SCHEMA:
        return "schema"
    for item in schema:
        if not isinstance(item, dict) or set(item) != {"path", "type", "top_level"}:
            return "schema"
        if not _safe_path(item.get("path")):
            return "path"
        if item.get("type") not in ALLOWED_VALUE_TYPES or not isinstance(item.get("top_level"), bool):
            return "schema"

    model_fields = value.get("model_fields")
    if not isinstance(model_fields, list) or len(model_fields) > MAX_MODEL_FIELDS:
        return "model"
    for item in model_fields:
        if not isinstance(item, dict) or set(item) != {"path", "value_state"}:
            return "model"
        if not _safe_path(item.get("path")):
            return "path"
        if item.get("value_state") not in ALLOWED_VALUE_STATES:
            return "model"

    enum_fields = value.get("enum_fields")
    if not isinstance(enum_fields, list) or len(enum_fields) > MAX_MODEL_FIELDS:
        return "enum"
    for item in enum_fields:
        if not isinstance(item, dict) or set(item) != {"path", "value"}:
            return "enum"
        path = _safe_path(item.get("path"))
        if not path:
            return "path"
        enum_key = path[-1].get("value") if path[-1].get("kind") == "key" else None
        allowed_values = ALLOWED_ENUM_VALUES_BY_KEY.get(enum_key)
        enum_value = item.get("value")
        if allowed_values is None:
            return "enum"
        if enum_key == "scene_location":
            if not isinstance(enum_value, int) or isinstance(enum_value, bool) or enum_value not in allowed_values:
                return "enum"
        elif not isinstance(enum_value, str) or enum_value not in allowed_values:
            return "enum"

    id_hashes = value.get("id_hashes")
    if not isinstance(id_hashes, list) or len(id_hashes) > MAX_ID_FIELDS:
        return "id_hash"
    for item in id_hashes:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            return "id_hash"
        if not _safe_path(item.get("path")):
            return "path"
        digest = item.get("sha256")
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            return "id_hash"

    usage = value.get("usage")
    if not isinstance(usage, list) or len(usage) > MAX_USAGE_FIELDS:
        return "usage"
    for item in usage:
        if not isinstance(item, dict) or set(item) != {"path", "value"}:
            return "usage"
        if not _safe_path(item.get("path")):
            return "path"
        number = item.get("value")
        if not isinstance(number, int) or isinstance(number, bool) or not 0 <= number <= 1_000_000_000:
            return "usage"
    return "projection_format"


def _projection_rejection_event(payload: object, stage_override: str | None = None) -> dict | None:
    """Return a minimal diagnostic only for a correctly scoped route event."""
    expected = {"kind", "request_seq", "route_name", "route", "route_sha256", "time_utc_ms", "projection"}
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("kind") != "upload_projection":
        return None
    route = payload.get("route")
    entry = ROUTES.get(route) if isinstance(route, str) else None
    if entry is None or payload.get("route_name") != entry["route_name"] or payload.get("route_sha256") != entry["path_sha256"]:
        return None
    seq, time_ms = payload.get("request_seq"), payload.get("time_utc_ms")
    if (not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= 1_000_000 or
            not isinstance(time_ms, int) or isinstance(time_ms, bool) or
            not 1_700_000_000_000 <= time_ms <= 2_100_000_000_000):
        return None
    projection = payload.get("projection")
    stage = stage_override or _projection_rejection_stage(projection)
    if stage not in PROJECTION_REJECTION_STAGES:
        return None
    parse_state = projection.get("parse_state") if isinstance(projection, dict) else None
    if parse_state not in ALLOWED_PARSE_STATES:
        parse_state = "unknown"
    return {"kind": "projection_rejected", "request_seq": seq,
            "route_name": entry["route_name"], "parse_state": parse_state, "stage": stage}


def sanitize(payload: object, target_pid: int = DEFAULT_PID) -> dict | None:
    """Project public JS records onto a strict, non-sensitive event schema."""
    if not isinstance(payload, dict):
        return None
    kind = payload.get("kind")
    if kind == "hook_install":
        expected_fields = {"kind", "pid", "hook_count", "hooks", "missing", "module_name",
                           "module_path_match", "module_size_match", "module_sha256_preflight",
                           "method_getter_ready", "header_getters_ready", "upload_api_ready",
                           "response_api_ready", "callback_manifest_count"}
        if set(payload) != expected_fields:
            return None
        hooks = payload.get("hooks")
        missing = payload.get("missing")
        count = payload.get("hook_count")
        event_pid = payload.get("pid")
        if not isinstance(event_pid, int) or isinstance(event_pid, bool) or event_pid != target_pid:
            return None
        if not isinstance(hooks, list) or not isinstance(missing, list):
            return None
        safe_hooks = {"Cronet_UrlRequest_InitWithParams", "Cronet_UrlRequest_Start",
                      "Cronet_UploadDataProvider_CreateWith", "Cronet_UploadDataProvider_GetLength",
                      "Cronet_UploadDataProvider_Read", "Cronet_UploadDataProvider_Rewind",
                      "Cronet_UploadDataProvider_Close", "Cronet_UploadDataSink_OnReadSucceeded",
                      "Cronet_UploadDataSink_OnReadError", "Cronet_UploadDataSink_OnRewindError"}
        if any(not isinstance(item, str) or item not in safe_hooks for item in hooks + missing):
            return None
        required_hooks = safe_hooks
        if (not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > len(safe_hooks) or
                not required_hooks.issubset(set(hooks)) or missing):
            return None
        if (payload.get("module_name") != "sscronet.dll" or
                payload.get("module_path_match") is not True or
                payload.get("module_size_match") is not True or
                payload.get("module_sha256_preflight") is not True):
            return None
        getter_flags = ("method_getter_ready", "header_getters_ready")
        if any(payload.get(flag) is not True for flag in getter_flags):
            return None
        if payload.get("upload_api_ready") is not True or payload.get("response_api_ready") is not False:
            return None
        callback_count = payload.get("callback_manifest_count")
        if not isinstance(callback_count, int) or isinstance(callback_count, bool) or not 0 <= callback_count <= 256:
            return None
        return {"kind": kind, "pid": target_pid, "hooks": sorted(set(hooks)),
                "missing": sorted(set(missing)), "hook_count": count,
                "module_name": "sscronet.dll", "module_path_match": True,
                "module_size_match": True, "module_sha256_preflight": True,
                "method_getter_ready": True, "header_getters_ready": True,
                "upload_api_ready": True, "response_api_ready": False,
                "callback_manifest_count": callback_count}

    if kind == "observer_ready":
        required_flags = ("process_image_path_match", "process_image_sha256_match",
                         "module_path_match", "module_sha256_match", "process_type_match",
                         "parent_pid_match", "upload_api_ready")
        if any(payload.get(flag) is not True for flag in required_flags):
            return None
        if payload.get("response_api_ready") is not False:
            return None
        count, seconds = payload.get("hook_count"), payload.get("observe_seconds")
        if not isinstance(count, int) or isinstance(count, bool) or not 7 <= count <= 72:
            return None
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= MAX_SECONDS:
            return None
        created = payload.get("created_local")
        if not isinstance(created, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?[+-]\d{2}:\d{2}", created):
            return None
        return {"kind": kind, "pid": target_pid, "created_local": created,
                "upload_api_ready": True, "response_api_ready": False,
                "hook_count": count, "observe_seconds": seconds,
                "auth_matching_enabled": payload.get("auth_matching_enabled") is True}

    if kind == "route_metadata":
        if set(payload) != {"kind", "request_seq", "time_utc_ms", "route", "method", "path_sha256", "origin", "header_names"}:
            return None
        seq, time_ms = payload.get("request_seq"), payload.get("time_utc_ms")
        route, method, path_hash = payload.get("route"), payload.get("method"), payload.get("path_sha256")
        entry = ROUTES.get(route) if isinstance(route, str) else None
        if entry is None or method != "POST" or path_hash != entry["path_sha256"]:
            return None
        origin = payload.get("origin")
        if origin != {"scheme": "https", "host": "trae-api-cn.mchost.guru", "port": 443}:
            return None
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= 1_000_000:
            return None
        if not isinstance(time_ms, int) or isinstance(time_ms, bool) or not 1_700_000_000_000 <= time_ms <= 2_100_000_000_000:
            return None
        names = payload.get("header_names")
        if not isinstance(names, list) or len(names) > 64 or any(not isinstance(x, str) or not HEADER_RE.fullmatch(x) for x in names):
            return None
        return {"kind": kind, "request_seq": seq, "time_utc_ms": time_ms,
                "route_name": entry["route_name"], "route": route,
                "path_sha256": path_hash, "method": method,
                "origin": origin, "header_names": sorted(set(names))}

    if kind == "upload_projection":
        if set(payload) != {"kind", "request_seq", "route_name", "route", "route_sha256", "time_utc_ms", "projection"}:
            return None
        seq, time_ms = payload.get("request_seq"), payload.get("time_utc_ms")
        route, route_name, route_hash = payload.get("route"), payload.get("route_name"), payload.get("route_sha256")
        entry = ROUTES.get(route) if isinstance(route, str) else None
        if entry is None or route_name != entry["route_name"] or route_hash != entry["path_sha256"]:
            return None
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= 1_000_000:
            return None
        if not isinstance(time_ms, int) or isinstance(time_ms, bool) or not 1_700_000_000_000 <= time_ms <= 2_100_000_000_000:
            return None
        projection = _sanitize_projection(payload.get("projection"))
        if projection is None:
            return None
        return {"kind": kind, "request_seq": seq, "route_name": route_name,
                "route": route, "route_sha256": route_hash,
                "time_utc_ms": time_ms, "projection": projection}

    if kind == "projection_rejected":
        if set(payload) != {"kind", "request_seq", "route_name", "parse_state", "stage"}:
            return None
        seq, route_name = payload.get("request_seq"), payload.get("route_name")
        parse_state, stage = payload.get("parse_state"), payload.get("stage")
        route_names = {item["route_name"] for item in ROUTES.values()}
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= 1_000_000:
            return None
        if route_name not in route_names or parse_state not in ALLOWED_PARSE_STATES | {"unknown"}:
            return None
        if stage not in PROJECTION_REJECTION_STAGES:
            return None
        return {"kind": kind, "request_seq": seq, "route_name": route_name,
                "parse_state": parse_state, "stage": stage}

    if kind == "auth_match":
        if set(payload) != {"kind", "request_seq", "header_name", "prefix_kind", "matched", "matched_sources", "reason"}:
            return None
        seq, name = payload.get("request_seq"), payload.get("header_name")
        prefix, matched, sources, reason = (payload.get("prefix_kind"), payload.get("matched"),
                                            payload.get("matched_sources"), payload.get("reason"))
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= 1_000_000:
            return None
        if name not in ALLOWED_AUTH_HEADERS or prefix not in ALLOWED_PREFIX_KINDS or not isinstance(matched, bool):
            return None
        if reason not in ALLOWED_AUTH_REASONS or not isinstance(sources, list) or len(sources) > 3:
            return None
        if any(source not in ALLOWED_AUTH_SOURCES for source in sources):
            return None
        safe_sources = sorted(set(sources))
        if matched != bool(safe_sources):
            return None
        return {"kind": kind, "request_seq": seq, "header_name": name,
                "prefix_kind": prefix, "matched": matched,
                "matched_sources": safe_sources, "reason": reason}

    if kind in {"callback_hook", "callback_attached"}:
        allowed_fields = ({"kind", "role", "module_name", "module_sha256", "attached", "rva"}
                          if kind == "callback_attached" else
                          {"kind", "role", "module_name", "module_sha256", "approved", "reason"})
        if set(payload) != allowed_fields:
            return None
        role, module_name, digest = payload.get("role"), payload.get("module_name"), payload.get("module_sha256")
        if (role not in ALLOWED_CALLBACK_ROLES or not isinstance(module_name, str) or
                module_name.casefold() not in KNOWN_CALLBACK_MODULES):
            return None
        if not isinstance(digest, str) or not MODULE_HASH_RE.fullmatch(digest):
            return None
        if kind == "callback_attached":
            if payload.get("attached") is not True:
                return None
            return {"kind": "callback_hook", "role": role, "module_name": module_name.casefold(),
                    "module_sha256": digest, "approved": True, "reason": "approved"}
        approved, reason = payload.get("approved"), payload.get("reason")
        if not isinstance(approved, bool) or reason not in {"approved", "module_unapproved", "range_invalid", "duplicate", "attach_failed"}:
            return None
        if approved != (reason == "approved"):
            return None
        return {"kind": kind, "role": role, "module_name": module_name.casefold(),
                "module_sha256": digest, "approved": approved, "reason": reason}

    if kind == "coverage_summary":
        coverage = payload.get("coverage")
        keys = {
            "init_calls", "start_calls", "route_eligible", "flow_started", "provider_bound",
            "get_length_seen", "read_wrapper", "read_callback", "read_ack", "upload_projection",
            "marker_candidate", "callback_attached", "callback_module_skip", "callback_alias_skip",
            "callback_attach_failure", "route_skip", "request_pointer_collision",
            "provider_pointer_collision", "pending_read_collision", "length_invalid", "buffer_invalid",
            "read_error", "rewind_invalidated", "close_invalidated", "auth_digest_sent",
            "auth_digest_skip", "output_cap_skip", "pending_at_end", "active_flows",
            "pending_reads", "route_counts",
        }
        if not isinstance(coverage, dict) or not set(coverage).issubset(keys):
            return None
        if any(k != "route_counts" and
               (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 1_000_000)
               for k, v in coverage.items()):
            return None
        route_counts = coverage.get("route_counts")
        safe_coverage = dict(coverage)
        if route_counts is not None:
            route_names = {item["route_name"] for item in ROUTES.values()}
            if not isinstance(route_counts, dict) or not set(route_counts).issubset(route_names):
                return None
            if any(not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 16 for v in route_counts.values()):
                return None
            safe_coverage["route_counts"] = dict(route_counts)
        return {"kind": kind, "coverage": safe_coverage}

    if kind in {"observer_timeout", "observer_stop", "script_unloaded", "target_detached",
                "session_detached", "cleanup_complete", "cleanup_incomplete", "no_session_attached"}:
        return {"kind": kind, "pid": target_pid}
    if kind == "process_check":
        return {"kind": kind, "pid": target_pid, "same_identity": payload.get("same_identity") is True}
    if kind == "output_summary":
        events, size, dropped = payload.get("events_written"), payload.get("bytes_written"), payload.get("events_dropped")
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (events, size, dropped)):
            return None
        if events > MAX_EVENTS + 16 or size > MAX_OUTPUT_BYTES or not isinstance(payload.get("cleanup_ok"), bool):
            return None
        return {"kind": kind, "events_written": events, "bytes_written": size,
                "events_dropped": dropped, "cleanup_ok": payload["cleanup_ok"]}
    if kind == "observer_error":
        phase, error_type, reason = payload.get("phase"), payload.get("error_type"), payload.get("reason")
        if phase not in {"preflight", "identity", "attach", "script", "readiness", "observe", "unload", "detach", "output"}:
            return None
        if error_type not in {"PermissionError", "PermissionDeniedError", "ProcessNotFoundError", "FileExistsError",
                              "FileNotFoundError", "TimeoutExpired", "TimeoutError", "OSError", "RuntimeError",
                              "ValueError", "JSONDecodeError", "OtherError", "ScriptError"}:
            return None
        if reason not in {"interpreter_mismatch", "agent_missing", "identity_tool_unavailable", "identity_query_failed",
                          "identity_shape_invalid", "process_identity_mismatch", "process_creation_mismatch",
                          "process_type_mismatch", "image_path_mismatch", "loaded_module_path_mismatch",
                          "image_hash_mismatch", "module_hash_mismatch", "callback_module_unapproved",
                          "callback_module_snapshot_changed", "auth_matcher_unavailable", "output_exists",
                          "frida_unavailable", "invalid_run_id", "output_create_failed", "seconds_out_of_range",
                          "hash_format", "hook_install_timeout", "upload_readiness_rejected", "ready_projection_rejected",
                          "process_identity_changed", "observer_failed", "script_failed", "cleanup_failed",
                          "attach_failed", "script_create_failed", "script_load_failed", "output_failed"}:
            return None
        return {"kind": kind, "phase": phase, "error_type": error_type, "reason": reason}
    return None


def _callback_module_snapshot(pid: int, install_root: Path) -> dict[str, dict]:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeError("identity_tool_unavailable")
    script = r"""
$ErrorActionPreference = 'Stop'
$targetPid = __PID__
$names = @('Trae CN.exe','sscronet.dll','aha_net.dll','TTNetDownloader.dll')
$mods = @(Get-Process -Id $targetPid -Module | Where-Object { $names -contains $_.ModuleName } | ForEach-Object {
  [pscustomobject]@{ name=[string]$_.ModuleName; path=[string]$_.FileName; memory_size=[long]$_.ModuleMemorySize }
})
ConvertTo-Json -InputObject $mods -Compress -Depth 4
""".replace("__PID__", str(pid))
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=20, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("identity_query_failed")
    rows = json.loads(result.stdout.strip())
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or len(rows) > MAX_CALLBACK_MODULES:
        raise RuntimeError("identity_shape_invalid")
    root_key = _path_key(install_root)
    modules = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("identity_shape_invalid")
        raw_name, raw_path = row.get("name"), row.get("path")
        mem_size = row.get("memory_size")
        if not isinstance(raw_name, str) or not isinstance(raw_path, str):
            continue
        name = raw_name.casefold()
        if name not in KNOWN_CALLBACK_MODULES:
            continue
        path = Path(raw_path)
        if _path_key(path.parent) != root_key:
            continue
        if not path.is_file() or not isinstance(mem_size, int) or isinstance(mem_size, bool) or not 0 < mem_size <= 1024 * 1024 * 1024:
            raise RuntimeError("identity_shape_invalid")
        digest = metadata_driver._file_sha256(path)
        expected = EXPECTED_FIXED_MODULE_HASHES.get(name)
        if expected is not None and digest.upper() != expected.upper():
            raise RuntimeError("callback_module_snapshot_changed")
        modules[name] = {"name": name, "path": str(path), "sha256": digest.upper(),
                         "memory_size": int(mem_size), "file_size": path.stat().st_size,
                         "exec_ranges": _pe_executable_ranges(path, int(mem_size))}
    if "trae cn.exe" not in modules or "sscronet.dll" not in modules:
        raise RuntimeError("callback_module_unapproved")
    return modules


def _pe_executable_ranges(path: Path, memory_size: int) -> list[tuple[int, int]]:
    """Return bounded PE section RVAs marked executable; no code is loaded."""
    try:
        with path.open("rb") as source:
            if source.read(2) != b"MZ":
                raise ValueError("identity_shape_invalid")
            source.seek(0x3C)
            raw = source.read(4)
            if len(raw) != 4:
                raise ValueError("identity_shape_invalid")
            pe_offset = struct.unpack("<I", raw)[0]
            if pe_offset > 16 * 1024 * 1024:
                raise ValueError("identity_shape_invalid")
            source.seek(pe_offset)
            header = source.read(24)
            if len(header) != 24 or header[:4] != b"PE\0\0":
                raise ValueError("identity_shape_invalid")
            sections = struct.unpack_from("<H", header, 6)[0]
            optional_size = struct.unpack_from("<H", header, 20)[0]
            if not 1 <= sections <= 96 or optional_size > 4096:
                raise ValueError("identity_shape_invalid")
            source.seek(pe_offset + 24 + optional_size)
            ranges = []
            for _ in range(sections):
                item = source.read(40)
                if len(item) != 40:
                    raise ValueError("identity_shape_invalid")
                virtual_size, virtual_address, raw_size = struct.unpack_from("<III", item, 8)
                characteristics = struct.unpack_from("<I", item, 36)[0]
                size = max(virtual_size, raw_size)
                end = virtual_address + size
                if characteristics & 0x20000000 and size > 0 and end <= memory_size:
                    ranges.append((virtual_address, end))
            if not ranges:
                raise ValueError("identity_shape_invalid")
            return ranges[:96]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("identity_shape_invalid") from exc


def _module_manifest_equal(left: dict, right: dict) -> bool:
    if set(left) != set(right):
        return False
    for name in left:
        a, b = left[name], right[name]
        if (a["sha256"] != b["sha256"] or a["memory_size"] != b["memory_size"] or
                a["exec_ranges"] != b["exec_ranges"] or _path_key(a["path"]) != _path_key(b["path"])):
            return False
    return True


def _ready_event_from_install(
    install: object, created_local: str, seconds: int, auth_matching_enabled: bool,
    target_pid: int = DEFAULT_PID,
) -> dict | None:
    """Build the ready event only from a fully validated public install event."""
    safe_install = sanitize(install, target_pid=target_pid)
    if safe_install is None or safe_install.get("kind") != "hook_install":
        return None
    if (safe_install.get("module_path_match") is not True or
            safe_install.get("module_sha256_preflight") is not True or
            safe_install.get("upload_api_ready") is not True or
            safe_install.get("response_api_ready") is not False):
        return None
    ready = {
        "kind": "observer_ready", "created_local": created_local,
        "upload_api_ready": True, "response_api_ready": False,
        "hook_count": safe_install["hook_count"], "observe_seconds": seconds,
        "process_image_path_match": True, "process_image_sha256_match": True,
        "module_path_match": True,
        "module_sha256_match": safe_install["module_sha256_preflight"],
        "process_type_match": True, "parent_pid_match": True,
        "auth_matching_enabled": auth_matching_enabled,
    }
    return ready if sanitize(ready, target_pid=target_pid) is not None else None


def _candidate_approval(payload: dict, modules: dict) -> dict | None:
    """Validate a synchronous callback attachment descriptor without logging RVA."""
    if (set(payload) != {"kind", "attached", "role", "module_name", "module_sha256", "rva"} or
            payload.get("kind") != "callback_attached" or payload.get("attached") is not True):
        return None
    role = payload.get("role")
    name = payload.get("module_name")
    digest = payload.get("module_sha256")
    rva = payload.get("rva")
    valid = (
        role in ALLOWED_CALLBACK_ROLES and isinstance(name, str) and name.casefold() in modules and
        isinstance(digest, str) and MODULE_HASH_RE.fullmatch(digest) and
        isinstance(rva, int) and not isinstance(rva, bool) and 0 <= rva <= (2**53 - 1)
    )
    if not valid:
        return None
    name = name.casefold()
    module = modules.get(name)
    if not module or digest.upper() != module["sha256"]:
        return None
    try:
        point = rva
        approved = point < module["memory_size"] and any(
            start <= point < end for start, end in module["exec_ranges"]
        )
    except Exception:
        approved = False
    if not approved:
        return None
    return {"kind": "callback_hook", "role": role, "module_name": name,
            "module_sha256": digest.upper(), "approved": True, "reason": "approved"}


def _consume_auth_digest(payload: dict, inventory) -> dict | None:
    """Consume a private Frida digest. Never return or retain the digest."""
    try:
        if set(payload) != {"kind", "request_seq", "header_name", "header_prefix_kind", "header_digest_sha256"}:
            return None
        if payload.get("kind") != "native_auth_digest":
            return None
        seq = payload.get("request_seq")
        header_name = payload.get("header_name")
        prefix_kind = payload.get("header_prefix_kind")
        digest = payload.get("header_digest_sha256")
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= 1_000_000:
            return None
        if header_name not in ALLOWED_AUTH_HEADERS or prefix_kind not in ALLOWED_PREFIX_KINDS:
            return None
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            return None
        if inventory is None:
            return {"kind": "auth_match", "request_seq": seq, "header_name": header_name,
                    "prefix_kind": prefix_kind, "matched": False,
                    "matched_sources": [], "reason": "auth_matching_disabled"}
        result = inventory.match_token_digest(digest, prefix_kind=prefix_kind, header_name=header_name)
        sources = sorted({source for source in result.matched_sources if source in ALLOWED_AUTH_SOURCES})
        reason = result.reason if result.reason in ALLOWED_AUTH_REASONS else "matcher_error"
        return {"kind": "auth_match", "request_seq": seq, "header_name": header_name,
                "prefix_kind": prefix_kind, "matched": bool(result.same_value and sources),
                "matched_sources": sources, "reason": reason}
    except Exception:
        return None
    finally:
        # This is a private message. Clearing the dict removes our retained
        # references before returning to the Frida event loop.
        payload.clear()


def _output_path(run_id: str) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise ValueError("invalid_run_id")
    return OUTPUT_BASE / run_id / "capture.jsonl"


def _event_line_size(payload: dict) -> int:
    line = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return len((line + "\n").encode("utf-8"))


def _admit_route_sequence(state: dict, route: str, seq: int) -> bool:
    """Count each exact request once, with fixed per-route and run caps."""
    route_sequences = state.get("route_sequences")
    sequence_route = state.get("sequence_route")
    route_overflow = state.get("route_overflow")
    if (not isinstance(route_sequences, dict) or route not in route_sequences or
            not isinstance(sequence_route, dict) or not isinstance(route_overflow, set)):
        return False
    previous = sequence_route.get(seq)
    if previous is not None and previous != route:
        return False
    if seq in route_overflow:
        return False
    if seq not in route_sequences[route]:
        accepted_total = sum(len(items) for items in route_sequences.values())
        if len(route_sequences[route]) >= 16 or accepted_total >= 48:
            route_overflow.add(seq)
            return False
        route_sequences[route].add(seq)
        sequence_route[seq] = route
    return True


def _self_test() -> int:
    projection = {
        "parse_state": "json", "body_bytes": 128, "marker_hit": True,
        "marker_semantics": "unverified", "marker_paths": [[{"kind": "key", "value": "messages"}, {"kind": "array_item"}, {"kind": "key", "value": "content"}]],
        "schema": [{"path": [{"kind": "key", "value": "messages"}], "type": "array", "top_level": True}],
        "model_fields": [{"path": [{"kind": "key", "value": "model_name"}], "value_state": "target"}],
        "enum_fields": [{"path": [{"kind": "key", "value": "reasoning_effort"}], "value": "low"}],
        "id_hashes": [{"path": [{"kind": "key", "value": "session_id"}], "sha256": "a" * 64}],
        "usage": [{"path": [{"kind": "key", "value": "prompt_tokens"}], "value": 12}],
    }
    event = {"kind": "upload_projection", "request_seq": 1,
             "route_name": "llm_utils_chat", "route": "/api/agent/v3/llm_utils_chat",
             "route_sha256": ROUTES["/api/agent/v3/llm_utils_chat"]["path_sha256"],
             "time_utc_ms": 1_800_000_000_000, "projection": projection}
    safe = sanitize(event)
    assert safe is not None and safe["projection"]["marker_semantics"] == "unverified"
    assert sanitize(dict(event, raw_body="must-not-print")) is None
    assert sanitize(dict(event, route="/api/agent/v3/not-allowlisted")) is None
    assert sanitize(dict(event, projection=dict(projection, untrusted_key="must-not-print"))) is None
    assert sanitize(dict(event, projection=dict(projection, marker_semantics="verified_user"))) is None
    assert sanitize(dict(event, projection=dict(projection, schema=[{
        "path": [{"kind": "key", "value": "secret_custom_key"}], "type": "string", "top_level": True
    }]))) is None
    assert sanitize(dict(event, projection=dict(projection, id_hashes=[{
        "path": [{"kind": "key", "value": "session_id"}], "sha256": "real-id"
    }]))) is None
    assert sanitize({"kind": "auth_match", "request_seq": 1, "header_name": "authorization",
                    "prefix_kind": "cloud_ide_jwt", "matched": True,
                    "matched_sources": ["proxy.token"], "reason": "matched",
                    "header_digest_sha256": "a" * 64, "header_value": "must-not-print"}) is None

    class FakeInventory:
        def __init__(self):
            self.seen = None

        def match_token_digest(self, digest, prefix_kind, header_name):
            self.seen = (digest, prefix_kind, header_name)
            class Result:
                same_value = True
                matched_sources = ("proxy.token",)
                reason = "matched"
            return Result()

    inventory = FakeInventory()
    private = {"kind": "native_auth_digest", "request_seq": 4, "header_name": "authorization",
               "header_prefix_kind": "cloud_ide_jwt", "header_digest_sha256": "b" * 64}
    auth_safe = _consume_auth_digest(private, inventory)
    assert auth_safe is not None and auth_safe["matched_sources"] == ["proxy.token"]
    assert inventory.seen == ("b" * 64, "cloud_ide_jwt", "authorization")
    assert not private
    encoded = json.dumps({"safe": safe, "auth": auth_safe}, separators=(",", ":"))
    for forbidden in ("header_digest_sha256", "must-not-print", "Cloud-IDE-JWT", "raw_body", "private_key"):
        assert forbidden not in encoded

    modules = {"aha_net.dll": {"sha256": "C" * 64, "memory_size": 0x100000,
                               "exec_ranges": [(0x1000, 0x1800)]}}
    candidate = {"kind": "callback_attached", "attached": True, "role": "read",
                 "module_name": "aha_net.dll", "module_sha256": "C" * 64, "rva": 0x1234}
    approved = _candidate_approval(candidate, modules)
    assert approved is not None and approved["approved"] is True
    assert "rva" not in json.dumps(approved)
    out_of_section = dict(candidate, rva=0x9000)
    assert _candidate_approval(out_of_section, modules) is None
    assert _candidate_approval(dict(candidate, rva=True), modules) is None
    route_state = {"route_sequences": {path: set() for path in ROUTES},
                   "sequence_route": {}, "route_overflow": set()}
    seq = 1
    route_names = list(ROUTES)
    for route in route_names:
        for _ in range(16):
            assert _admit_route_sequence(route_state, route, seq)
            assert _admit_route_sequence(route_state, route, seq)
            seq += 1
    assert not _admit_route_sequence(route_state, route_names[0], seq)
    assert not _admit_route_sequence(route_state, route_names[1], 1)
    print(json.dumps({"self_test": "passed", "cases": 12}, separators=(",", ":")))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded, upload-only native request observer")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--observe-once", action="store_true")
    parser.add_argument("--pid", type=int, default=DEFAULT_PID)
    parser.add_argument("--parent-pid", type=int, default=DEFAULT_PARENT_PID)
    parser.add_argument("--expected-created", default=DEFAULT_CREATED)
    parser.add_argument("--image-path", type=Path, default=DEFAULT_IMAGE_PATH)
    parser.add_argument("--image-sha256", default=DEFAULT_IMAGE_SHA256)
    parser.add_argument("--module-path", type=Path, default=DEFAULT_MODULE_PATH)
    parser.add_argument("--module-sha256", default=DEFAULT_MODULE_SHA256)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--run-id")
    parser.add_argument("--read-auth-candidates", action="store_true",
                        help="explicitly read only local candidate token fields for digest matching")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not 1 <= args.seconds <= MAX_SECONDS:
        print(json.dumps({"kind": "preflight_rejected", "reason": "seconds_out_of_range"}), flush=True)
        return 2
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.image_sha256) or not re.fullmatch(r"[0-9a-fA-F]{64}", args.module_sha256):
        print(json.dumps({"kind": "preflight_rejected", "reason": "hash_format"}), flush=True)
        return 2
    try:
        output_path = _output_path(args.run_id)
        if not AGENT_PATH.is_file() or not CORE_PATH.is_file():
            raise RuntimeError("agent_missing")
        if Path(sys.executable).resolve().as_posix().casefold() != EXPECTED_PYTHON.resolve().as_posix().casefold():
            raise RuntimeError("interpreter_mismatch")
        identity_args = argparse.Namespace(
            pid=args.pid, parent_pid=args.parent_pid, expected_created=args.expected_created,
            image_path=args.image_path, image_sha256=args.image_sha256,
            module_path=args.module_path, module_sha256=args.module_sha256,
        )
        identity = metadata_driver._identity_preflight(identity_args)
        callback_modules = _callback_module_snapshot(args.pid, args.image_path.parent)
    except Exception as exc:
        reason = getattr(exc, "args", [None])[0]
        allowed = {"invalid_run_id", "agent_missing", "interpreter_mismatch", "identity_tool_unavailable",
                   "identity_query_failed", "identity_shape_invalid", "process_identity_mismatch",
                   "process_creation_mismatch", "process_type_mismatch", "image_path_mismatch",
                   "loaded_module_path_mismatch", "image_hash_mismatch", "module_hash_mismatch",
                   "callback_module_snapshot_changed", "callback_module_unapproved"}
        print(json.dumps({"kind": "preflight_rejected", "reason": reason if reason in allowed else "identity_gate_failed"},
                         separators=(",", ":")), flush=True)
        return 2

    inventory = None
    auth_enabled = False
    if args.read_auth_candidates:
        try:
            from native_auth_matcher import load_candidate_inventory
            inventory = load_candidate_inventory()
            auth_enabled = True
        except Exception:
            inventory = None
            auth_enabled = False

    try:
        import frida
    except Exception:
        inventory = None
        print(json.dumps({"kind": "preflight_rejected", "reason": "frida_unavailable"}), flush=True)
        return 2

    try:
        output_path.parent.mkdir(parents=True, exist_ok=False)
        output = output_path.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        inventory = None
        print(json.dumps({"kind": "preflight_rejected", "reason": "output_exists"}), flush=True)
        return 2
    except Exception:
        inventory = None
        print(json.dumps({"kind": "preflight_rejected", "reason": "output_create_failed"}), flush=True)
        return 2

    lock = threading.Lock()
    state = {"ready": False, "hook_install": None, "coverage": None, "script": None,
             "auth_digest_count": 0, "callback_attached_count": 0, "raw_messages": 0,
             "projection_rejection_diagnostics": 0,
             "route_sequences": {path: set() for path in ROUTES}, "sequence_route": {},
             "route_overflow": set()}
    installed_event = threading.Event()
    detached_event = threading.Event()
    active = []
    counters = {"events_written": 0, "bytes_written": 0, "events_dropped": 0}
    output_closed = False
    output_failed = False
    stdout_failed = False
    cleanup_ok = True
    exit_code = 0

    def emit(payload: dict, critical: bool = False) -> bool:
        nonlocal output_failed, stdout_failed
        try:
            safe = sanitize(payload, target_pid=args.pid)
            if safe is None:
                counters["events_dropped"] += 1
                return False
            line = json.dumps(safe, ensure_ascii=True, separators=(",", ":"))
            size = len((line + "\n").encode("utf-8"))
            with lock:
                if output_closed or output_failed:
                    counters["events_dropped"] += 1
                    return False
                if size > MAX_LINE_BYTES or counters["events_written"] >= MAX_EVENTS + 16:
                    counters["events_dropped"] += 1
                    return False
                limit = MAX_OUTPUT_BYTES if critical else MAX_OUTPUT_BYTES - MAX_RESERVED_BYTES
                if counters["bytes_written"] + size > limit:
                    counters["events_dropped"] += 1
                    return False
                try:
                    output.write(line + "\n")
                    output.flush()
                except Exception:
                    output_failed = True
                    counters["events_dropped"] += 1
                    return False
                counters["events_written"] += 1
                counters["bytes_written"] += size
                if not stdout_failed:
                    try:
                        print(line, flush=True)
                    except Exception:
                        stdout_failed = True
            return True
        except BaseException:
            output_failed = True
            counters["events_dropped"] += 1
            return False

    def on_message(message, _data):
        nonlocal exit_code
        try:
            state["raw_messages"] += 1
            if state["raw_messages"] > 2048:
                return
            if message.get("type") == "send":
                payload = message.get("payload")
                if not isinstance(payload, dict):
                    return
                kind = payload.get("kind")
                if kind == "native_auth_digest":
                    state["auth_digest_count"] += 1
                    if state["auth_digest_count"] > MAX_PENDING_AUTH_DIGESTS:
                        payload.clear()
                        return
                    safe_auth = _consume_auth_digest(payload, inventory)
                    if safe_auth is not None:
                        emit(safe_auth)
                    return
                if kind == "callback_candidate":
                    # Unapproved candidates are internal diagnostics only.
                    payload.clear()
                    return
                if kind == "callback_attached":
                    state["callback_attached_count"] += 1
                    if state["callback_attached_count"] > 128:
                        payload.clear()
                        return
                    safe_status = _candidate_approval(payload, callback_modules)
                    if safe_status is not None:
                        emit(safe_status)
                    payload.clear()
                    return
                if kind in {"route_metadata", "upload_projection"}:
                    safe_route_event = sanitize(payload, target_pid=args.pid)
                    if safe_route_event is None:
                        counters["events_dropped"] += 1
                        if (kind == "upload_projection" and
                                state["projection_rejection_diagnostics"] < MAX_PROJECTION_REJECTION_DIAGNOSTICS):
                            diagnostic = _projection_rejection_event(payload)
                            if diagnostic is not None:
                                state["projection_rejection_diagnostics"] += 1
                                emit(diagnostic)
                        payload.clear()
                        return
                    route = safe_route_event["route"]
                    seq = safe_route_event["request_seq"]
                    if not _admit_route_sequence(state, route, seq):
                        counters["events_dropped"] += 1
                        if (kind == "upload_projection" and
                                state["projection_rejection_diagnostics"] < MAX_PROJECTION_REJECTION_DIAGNOSTICS):
                            diagnostic = _projection_rejection_event(payload, stage_override="sequence")
                            if diagnostic is not None:
                                state["projection_rejection_diagnostics"] += 1
                                emit(diagnostic)
                        payload.clear()
                        return
                    if kind == "upload_projection":
                        safe_size = _event_line_size(safe_route_event)
                        with lock:
                            output_bytes = counters["bytes_written"]
                        reject_stage = None
                        if safe_size > MAX_LINE_BYTES:
                            reject_stage = "line_limit"
                        elif output_bytes + safe_size > MAX_OUTPUT_BYTES - MAX_RESERVED_BYTES:
                            reject_stage = "output_limit"
                        if reject_stage is not None:
                            counters["events_dropped"] += 1
                            if state["projection_rejection_diagnostics"] < MAX_PROJECTION_REJECTION_DIAGNOSTICS:
                                diagnostic = _projection_rejection_event(payload, stage_override=reject_stage)
                                if diagnostic is not None:
                                    state["projection_rejection_diagnostics"] += 1
                                    emit(diagnostic)
                            payload.clear()
                            return
                    emit(payload, critical=kind == "route_metadata")
                    payload.clear()
                    return
                if kind == "hook_install":
                    state["hook_install"] = sanitize(payload, target_pid=args.pid)
                    installed_event.set()
                elif kind == "coverage_summary":
                    safe = sanitize(payload, target_pid=args.pid)
                    state["coverage"] = safe.get("coverage") if safe else None
                critical = kind in {"hook_install", "coverage_summary", "observer_timeout"}
                emit(payload, critical=critical)
                payload.clear()
            elif message.get("type") == "error":
                emit({"kind": "observer_error", "phase": "script", "error_type": "ScriptError", "reason": "script_failed"}, critical=True)
        except BaseException:
            # Never serialize callback payloads or exception messages.
            exit_code = 1

    phase = "attach"
    try:
        device = frida.get_local_device()
        session = device.attach(args.pid)
        session_item = {"session": session, "script": None}
        active.append(session_item)

        def on_detached(*_args):
            detached_event.set()
            emit({"kind": "target_detached"}, critical=True)

        session.on("detached", on_detached)
        phase = "identity"
        attached_identity = metadata_driver._identity_preflight(identity_args)
        attached_modules = _callback_module_snapshot(args.pid, args.image_path.parent)
        if attached_identity != identity or not _module_manifest_equal(callback_modules, attached_modules):
            raise RuntimeError("process_identity_changed")

        cronet_module = callback_modules["sscronet.dll"]
        config = {
            "pid": args.pid, "expected_module_path": cronet_module["path"],
            "expected_module_size": cronet_module["memory_size"],
            "expected_module_sha256": cronet_module["sha256"].lower(),
            "install_root": str(args.image_path.parent), "max_seconds": args.seconds,
            "marker": "TRAE_NATIVE_20261027_B_OK", "target_model": "deepseek-v4.1-flash",
            "callback_modules": [
                {"module_name": item["name"], "module_path": item["path"],
                 "module_sha256": item["sha256"].lower(), "memory_size": item["memory_size"],
                 "executable_ranges": [{"rva_start": start, "rva_end": end}
                                        for start, end in item["exec_ranges"]]}
                for item in callback_modules.values()
            ],
            "route_allowlist": [
                {"path": path, "path_sha256": item["path_sha256"], "route_name": item["route_name"],
                 "host": "trae-api-cn.mchost.guru", "port": 443, "scheme": "https", "method": "POST"}
                for path, item in ROUTES.items()
            ],
            "auth_matching_enabled": auth_enabled,
        }
        phase = "script"
        source = CORE_PATH.read_text(encoding="utf-8") + "\n" + AGENT_PATH.read_text(encoding="utf-8")
        source += "\nNativeUploadObserver.install(" + json.dumps(config, ensure_ascii=True) + ");\n"
        script = session.create_script(source, runtime="qjs")
        session_item["script"] = script
        state["script"] = script
        script.on("message", on_message)
        script.load()
        phase = "readiness"
        if not installed_event.wait(15):
            raise RuntimeError("hook_install_timeout")
        install = state["hook_install"] or {}
        ready = _ready_event_from_install(
            install, identity["created_local"], args.seconds, auth_enabled, target_pid=args.pid,
        )
        if ready is None:
            raise RuntimeError("upload_readiness_rejected")
        if not emit(ready, critical=True):
            raise RuntimeError("ready_projection_rejected")
        state["ready"] = True
        phase = "observe"
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline and not detached_event.is_set():
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        if not detached_event.is_set():
            emit({"kind": "observer_timeout"}, critical=True)
    except KeyboardInterrupt:
        emit({"kind": "observer_stop"}, critical=True)
    except Exception as exc:
        exit_code = 1
        phase_map = {"attach": "attach_failed", "identity": "process_identity_changed",
                     "script": "script_failed", "readiness": "upload_readiness_rejected",
                     "observe": "observer_failed"}
        raw_reason = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "observer_failed"
        allowed = {"process_identity_changed", "hook_install_timeout", "upload_readiness_rejected",
                   "ready_projection_rejected", "attach_failed", "script_create_failed", "script_load_failed"}
        emit({"kind": "observer_error", "phase": phase,
              "error_type": type(exc).__name__ if type(exc).__name__ in {"PermissionError", "ProcessNotFoundError", "TimeoutError", "OSError", "RuntimeError", "ValueError", "OtherError"} else "OtherError",
              "reason": raw_reason if raw_reason in allowed else phase_map.get(phase, "observer_failed")}, critical=True)
    finally:
        # Each cleanup action is isolated so one reporting or unload failure
        # cannot skip the remaining detach/close operations.
        for item in reversed(active):
            if item["script"] is not None:
                try:
                    item["script"].unload()
                    emit({"kind": "script_unloaded"}, critical=True)
                except Exception:
                    cleanup_ok = False
                    exit_code = 1
                try:
                    item["session"].detach()
                    emit({"kind": "session_detached"}, critical=True)
                except Exception:
                    cleanup_ok = False
                    exit_code = 1
            else:
                try:
                    item["session"].detach()
                    emit({"kind": "session_detached"}, critical=True)
                except Exception:
                    cleanup_ok = False
                    exit_code = 1
        try:
            final_identity = metadata_driver._identity_preflight(identity_args)
            final_modules = _callback_module_snapshot(args.pid, args.image_path.parent)
            same_identity = final_identity == identity and _module_manifest_equal(callback_modules, final_modules)
        except Exception:
            same_identity = False
        emit({"kind": "process_check", "same_identity": same_identity}, critical=True)
        if not same_identity:
            cleanup_ok = False
        coverage = state.get("coverage")
        if isinstance(coverage, dict):
            emit({"kind": "coverage_summary", "coverage": coverage}, critical=True)
        if not active:
            emit({"kind": "no_session_attached"}, critical=True)
        elif cleanup_ok:
            emit({"kind": "cleanup_complete"}, critical=True)
        else:
            emit({"kind": "cleanup_incomplete"}, critical=True)
        with lock:
            try:
                if not output_closed:
                    output.flush()
                    output.close()
                    output_closed = True
            except Exception:
                cleanup_ok = False
                exit_code = 1
        inventory = None
    # The disk summary is a separate final record; its own bytes are not
    # included in these counters, matching the metadata observer convention.
    try:
        summary = {"kind": "output_summary", "events_written": counters["events_written"],
                   "bytes_written": counters["bytes_written"], "events_dropped": counters["events_dropped"],
                   "cleanup_ok": cleanup_ok}
        safe = sanitize(summary, target_pid=args.pid)
        if safe is not None:
            with output_path.open("a", encoding="utf-8", newline="\n") as final_output:
                final_output.write(json.dumps(safe, separators=(",", ":")) + "\n")
        print(json.dumps(safe or {"kind": "output_summary", "cleanup_ok": False}, separators=(",", ":")), flush=True)
    except Exception:
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
