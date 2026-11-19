"""Bounded, fail-closed driver for the passive Cronet metadata observer.

The driver emits only sanitized route metadata. It does not read credentials,
HTTP header values, request/response bodies, or raw URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = Path(__file__).with_name("native_metadata_observer.js")
OUTPUT_BASE = ROOT / "logs" / "native_metadata_observer_20261027"

DEFAULT_PID = 144016
DEFAULT_PARENT_PID = 251084
DEFAULT_CREATED = "2026-10-27T09:33:35.107913+08:00"
DEFAULT_IMAGE_PATH = Path(r"D:\Users\marcus\AppData\Local\Programs\Trae CN\Trae CN.exe")
DEFAULT_IMAGE_SHA256 = "6069AC7FB5D1E20FA08A1635CA4613957EB81F9DD670DCA5CBA844CAC1062CA4"
DEFAULT_MODULE_PATH = Path(r"D:\Users\marcus\AppData\Local\Programs\Trae CN\sscronet.dll")
DEFAULT_MODULE_SHA256 = "288F987E64107A603CAE0E04D3282935B4017DC1C042EA579334DA49984FB79A"
DEFAULT_PROCESS_TYPE = "utility"
DEFAULT_UTILITY_SUBTYPE = "network.mojom.NetworkService"
EXPECTED_PYTHON = Path(r"E:\tools\frida\venv\Scripts\python.exe")

KNOWN_HOSTS = {"trae-api-cn.mchost.guru", "api.trae.cn", "api.trae.com.cn"}
HOOKS = {"Cronet_UrlRequest_InitWithParams", "Cronet_UrlRequest_Start"}
HOOK_MISSING = HOOKS | {"pid_mismatch", "sscronet_missing", "module_path_mismatch", "hook_export_unavailable_or_alias"}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "unknown"}
HEADER_NAME_RE = re.compile(r"[!#$%&'*+.^_`|~0-9a-z-]{1,64}\Z")
STATIC_PATH_TOKENS = {
    "api", "ide", "agent", "inner", "v1", "v2", "v3", "chat", "ping", "model_list",
    "get_detail_param", "batch_get_detail_param", "llm_raw_chat", "llm_raw_chat_prompt",
    "web_search", "create_agent_task", "commit_toolcall_result", "interrupt",
    "resume_agent_task", "get_resume_agent_task_status", "query_history_state",
    "sync_history_state", "compact", "llm_utils_chat", "workflow", "start",
    "commit_toolcall", "use_fast_request", "generate_summary", "dsl", "logs",
    "subscribe", "templates", "render", "resources", "custom_model_connectivity_check",
    "generated_skill", "restore_pending", "dismiss_pending", "get_pending", "list_pending",
}
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_SEGMENTS = 32
MAX_HEADERS = 64
MAX_EVENTS = 512
MAX_OUTPUT_BYTES = 256 * 1024
MAX_LINE_BYTES = 4096
RESERVED_OUTPUT_BYTES = 8192
MAX_OBSERVE_SECONDS = 300
ERROR_TYPES = {
    "PermissionError", "PermissionDeniedError", "ProcessNotFoundError", "FileExistsError",
    "FileNotFoundError", "TimeoutExpired", "TimeoutError", "OSError",
    "RuntimeError", "ValueError", "JSONDecodeError", "InvalidOperationError",
    "TransportError", "ScriptError", "OtherError",
}
ERROR_REASONS = {
    "interpreter_mismatch", "agent_missing", "identity_tool_unavailable",
    "identity_query_failed", "identity_shape_invalid", "process_identity_mismatch",
    "process_creation_mismatch", "process_type_mismatch", "image_path_mismatch",
    "loaded_module_path_mismatch", "image_hash_mismatch", "module_hash_mismatch",
    "output_exists", "frida_unavailable", "invalid_run_id", "output_create_failed",
    "seconds_out_of_range", "hash_format", "hook_install_timeout",
    "metadata_readiness_rejected", "ready_projection_rejected", "process_identity_changed",
    "interrupted", "observer_failed", "script_failed", "cleanup_failed",
    "attach_failed", "script_create_failed", "script_load_failed",
    "output_failed", "identity_gate_failed",
}

COVERAGE_KEYS = {
    "init_calls", "start_calls", "route_metadata", "other_origin", "invalid_url",
    "method_unreadable", "header_names_unreadable", "too_many_headers",
    "pointer_collision", "pending_cap_skip", "ambiguous_start_skip",
    "start_without_init", "start_failed", "pending_at_end", "output_cap_skip",
}


def _valid_origin(value, known_only=False):
    if not isinstance(value, dict):
        return None
    scheme, host, port = value.get("scheme"), value.get("host"), value.get("port")
    if scheme not in {"http", "https"}:
        return None
    if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9.-]{1,253}", host):
        return None
    if host.startswith(".") or host.endswith(".") or ".." in host:
        return None
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return None
    if known_only and (host not in KNOWN_HOSTS or scheme != "https" or port != 443):
        return None
    if not known_only and (
        host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home"))
        or "." not in host
        or re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", host)
    ):
        return None
    return {"scheme": scheme, "host": host, "port": port}


def sanitize(payload, target_pid=DEFAULT_PID):
    """Project a Frida message onto the small, non-sensitive output schema."""
    if not isinstance(payload, dict):
        return None
    kind = payload.get("kind")
    if kind == "hook_install":
        hooks, missing = payload.get("hooks"), payload.get("missing")
        module_name = payload.get("module_name")
        count = payload.get("hook_count")
        if not isinstance(hooks, list) or not isinstance(missing, list):
            return None
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 2:
            return None
        if module_name not in {"sscronet.dll", None}:
            return None
        if any(not isinstance(item, str) or item not in HOOK_MISSING for item in hooks + missing):
            return None
        safe_hooks = sorted(set(hooks))
        safe_missing = sorted(set(missing))
        if count != len(safe_hooks):
            return None
        return {
            "kind": kind, "pid": target_pid, "hook_count": count,
            "hooks": safe_hooks, "missing": safe_missing,
            "module_name": module_name,
            "module_path_match": payload.get("module_path_match") is True,
            "method_getter_ready": payload.get("method_getter_ready") is True,
            "header_getters_ready": payload.get("header_getters_ready") is True,
            "body_api_ready": payload.get("body_api_ready") is True,
        }
    if kind == "request_metadata":
        origin = _valid_origin(payload.get("origin"), known_only=True)
        seq, time_ms = payload.get("request_seq"), payload.get("time_utc_ms")
        path_hash, segments = payload.get("path_sha256"), payload.get("path_segments")
        method, names, name_status = (
            payload.get("method"), payload.get("configured_header_names"),
            payload.get("header_names_status"),
        )
        if origin is None:
            return None
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= 1_000_000:
            return None
        if not isinstance(time_ms, int) or isinstance(time_ms, bool) or not 1_700_000_000_000 <= time_ms <= 2_100_000_000_000:
            return None
        if not isinstance(path_hash, str) or not HASH_RE.fullmatch(path_hash):
            return None
        if not isinstance(segments, list) or len(segments) > MAX_SEGMENTS:
            return None
        safe_segments = []
        for segment in segments:
            if not isinstance(segment, dict):
                return None
            if segment.get("kind") == "static":
                value = segment.get("value")
                index = segment.get("index")
                if (not isinstance(value, str) or value not in STATIC_PATH_TOKENS
                        or not isinstance(index, int) or isinstance(index, bool)
                        or not 1 <= index <= MAX_SEGMENTS):
                    return None
                safe_segments.append({"kind": "static", "index": index, "value": value})
            elif segment.get("kind") == "hash":
                digest = segment.get("sha256")
                index = segment.get("index")
                if (not isinstance(digest, str) or not HASH_RE.fullmatch(digest)
                        or not isinstance(index, int) or isinstance(index, bool)
                        or not 1 <= index <= MAX_SEGMENTS):
                    return None
                safe_segments.append({"kind": "hash", "index": index, "sha256": digest})
            else:
                return None
        if method not in METHODS:
            return None
        if name_status not in {"read", "unavailable", "over_limit", "unreadable"}:
            return None
        if not isinstance(names, list) or len(names) > MAX_HEADERS:
            return None
        if any(not isinstance(name, str) or not HEADER_NAME_RE.fullmatch(name) for name in names):
            return None
        safe_names = sorted(set(names))
        if name_status != "read" and safe_names:
            return None
        if payload.get("body_read") is not False or payload.get("response_read") is not False:
            return None
        return {
            "kind": kind, "request_seq": seq, "time_utc_ms": time_ms,
            "origin": origin, "path_sha256": path_hash,
            "path_segments": safe_segments, "method": method,
            "configured_header_names": safe_names,
            "header_names_status": name_status,
            "body_read": False, "response_read": False,
        }
    if kind == "other_origin":
        seq = payload.get("request_seq")
        status = payload.get("origin_status")
        origin = _valid_origin(payload.get("origin")) if status == "public" else None
        method = payload.get("method")
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= 1_000_000:
            return None
        if status not in {"public", "hidden"}:
            return None
        if status == "public" and origin is None:
            return None
        if status == "hidden" and payload.get("origin") is not None:
            return None
        if method not in METHODS:
            return None
        if payload.get("path_read") is not False or payload.get("headers_read") is not False:
            return None
        return {
            "kind": kind, "request_seq": seq, "origin": origin,
            "origin_status": status, "method": method,
            "path_read": False, "headers_read": False,
        }
    if kind == "coverage_summary":
        coverage = payload.get("coverage")
        if not isinstance(coverage, dict):
            return None
        safe = {}
        for key in COVERAGE_KEYS:
            value = coverage.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1_000_000:
                return None
            safe[key] = value
        return {"kind": kind, "coverage": safe}
    if kind == "observer_ready":
        seconds = payload.get("observe_seconds")
        count = payload.get("hook_count")
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= MAX_OBSERVE_SECONDS:
            return None
        if count != 2 or payload.get("body_api_ready") is not False:
            return None
        if payload.get("method_getter_ready") is not True or payload.get("header_getters_ready") is not True:
            return None
        if any(payload.get(key) is not True for key in (
            "process_image_path_match", "process_image_sha256_match",
            "module_path_match", "module_sha256_match", "process_type_match",
            "parent_pid_match",
        )):
            return None
        created = payload.get("created_local")
        if not isinstance(created, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?[+-]\d{2}:\d{2}", created):
            return None
        return {
            "kind": kind, "pid": target_pid, "created_local": created,
            "process_image_path_match": True, "process_image_sha256_match": True,
            "module_path_match": True, "module_sha256_match": True,
            "process_type_match": True, "parent_pid_match": True,
            "hook_count": 2,
            "method_getter_ready": payload.get("method_getter_ready") is True,
            "header_getters_ready": payload.get("header_getters_ready") is True,
            "body_api_ready": False, "observe_seconds": seconds,
            "scope": "url_origin_path_method_header_names_only",
        }
    if kind == "process_check":
        return {"kind": kind, "pid": target_pid, "same_identity": payload.get("same_identity") is True}
    if kind in {"observer_timeout", "observer_stop", "target_detached", "script_unloaded",
                "session_detached", "no_session_attached", "cleanup_complete", "cleanup_incomplete"}:
        return {"kind": kind, "pid": target_pid}
    if kind == "observer_error":
        phase = payload.get("phase")
        error_type = payload.get("error_type")
        reason = payload.get("reason")
        if phase not in {"preflight", "identity", "attach", "script", "readiness", "observe", "unload", "detach", "output"}:
            return None
        if error_type not in ERROR_TYPES or reason not in ERROR_REASONS:
            return None
        return {"kind": kind, "pid": target_pid, "phase": phase,
                "error_type": error_type, "reason": reason}
    if kind == "output_summary":
        events = payload.get("events_before_summary")
        size = payload.get("bytes_before_summary")
        dropped = payload.get("events_dropped")
        cleanup_ok = payload.get("cleanup_ok")
        output_ok = payload.get("output_ok")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (events, size, dropped)):
            return None
        if size > MAX_OUTPUT_BYTES or events > MAX_EVENTS + 16 or not isinstance(cleanup_ok, bool) or not isinstance(output_ok, bool):
            return None
        output_ref = payload.get("output_ref")
        if not isinstance(output_ref, str) or not re.fullmatch(
            r"logs/native_metadata_observer_20261027/[A-Za-z0-9_-]{1,64}/metadata\.jsonl", output_ref
        ):
            return None
        return {"kind": kind, "events_written": events, "bytes_written": size,
                "events_dropped": dropped, "cleanup_ok": cleanup_ok,
                "output_ok": output_ok, "output_ref": output_ref}
    return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _powershell_identity(pid: int) -> dict:
    """Read only process identity fields; never return the full command line."""
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeError("identity_tool_unavailable")
    script = r"""
$ErrorActionPreference = 'Stop'
$targetPid = __PID__
$p = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $targetPid)
if (-not $p) { throw 'process_missing' }
$cmd = [string]$p.CommandLine
$type = [regex]::Match($cmd, '(?:^|\s)--type=([^\s"]+)').Groups[1].Value
$subtype = [regex]::Match($cmd, '(?:^|\s)--utility-sub-type=([^\s"]+)').Groups[1].Value
$module = Get-Process -Id $targetPid -Module | Where-Object { $_.ModuleName -ieq 'sscronet.dll' } | Select-Object -First 1
$modulePath = if ($module) { [string]$module.FileName } else { '' }
$created = ([datetime]$p.CreationDate).ToString('o')
[pscustomobject]@{
  pid = [int]$p.ProcessId
  parent_pid = [int]$p.ParentProcessId
  created_local = $created
  image_path = [string]$p.ExecutablePath
  process_type = $type
  utility_subtype = $subtype
  module_path = $modulePath
} | ConvertTo-Json -Compress
""".replace("__PID__", str(pid))
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("identity_query_failed")
    data = json.loads(result.stdout.strip())
    if not isinstance(data, dict):
        raise RuntimeError("identity_shape_invalid")
    return data


def _path_key(path) -> str:
    return str(path).replace("/", "\\").casefold()


def _parse_local_created(value: str) -> datetime:
    """Parse PowerShell round-trip timestamps on Python 3.10 (max 6 us digits)."""
    if not isinstance(value, str):
        raise ValueError("identity_shape_invalid")
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,7}))?([+-]\d{2}:\d{2})",
        value,
    )
    if not match:
        raise ValueError("identity_shape_invalid")
    whole, fraction, offset = match.groups()
    if fraction is None:
        normalized = whole + offset
    else:
        normalized = whole + "." + fraction[:6].ljust(6, "0") + offset
    return datetime.fromisoformat(normalized)


def _output_path_for_run(run_id: str, output_base: Path = OUTPUT_BASE) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise ValueError("invalid_run_id")
    return output_base / run_id / "metadata.jsonl"


def _create_output_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=False)
    return path.open("x", encoding="utf-8", newline="\n")


def _safe_error_type(exc) -> str:
    name = type(exc).__name__
    return name if name in ERROR_TYPES else "OtherError"


def _safe_reason(exc, allowed=None) -> str:
    candidates = ERROR_REASONS if allowed is None else allowed
    if isinstance(exc, RuntimeError) and exc.args and isinstance(exc.args[0], str):
        name = exc.args[0]
        if name in candidates:
            return name
    return "observer_failed"


def _error_record(exc, phase, fallback_reason):
    safe_phase = phase if phase in {
        "preflight", "identity", "attach", "script", "readiness", "observe",
        "unload", "detach", "output",
    } else "observe"
    reason = _safe_reason(exc)
    if reason == "observer_failed":
        reason = fallback_reason if fallback_reason in ERROR_REASONS else "observer_failed"
    return {
        "kind": "observer_error", "phase": safe_phase,
        "error_type": _safe_error_type(exc), "reason": reason,
    }


def _identity_preflight(args) -> dict:
    if Path(sys.executable).resolve().as_posix().casefold() != EXPECTED_PYTHON.resolve().as_posix().casefold():
        raise RuntimeError("interpreter_mismatch")
    if not AGENT_PATH.is_file():
        raise RuntimeError("agent_missing")
    actual = _powershell_identity(args.pid)
    expected_created = _parse_local_created(args.expected_created)
    actual_created = _parse_local_created(actual["created_local"])
    if actual.get("pid") != args.pid or actual.get("parent_pid") != args.parent_pid:
        raise RuntimeError("process_identity_mismatch")
    if abs((actual_created - expected_created).total_seconds()) > 1.0:
        raise RuntimeError("process_creation_mismatch")
    if actual.get("process_type") != DEFAULT_PROCESS_TYPE or actual.get("utility_subtype") != DEFAULT_UTILITY_SUBTYPE:
        raise RuntimeError("process_type_mismatch")
    if _path_key(actual.get("image_path", "")) != _path_key(args.image_path):
        raise RuntimeError("image_path_mismatch")
    if _path_key(actual.get("module_path", "")) != _path_key(args.module_path):
        raise RuntimeError("loaded_module_path_mismatch")
    if _file_sha256(Path(actual["image_path"])) != args.image_sha256.upper():
        raise RuntimeError("image_hash_mismatch")
    if _file_sha256(Path(actual["module_path"])) != args.module_sha256.upper():
        raise RuntimeError("module_hash_mismatch")
    return actual


def _bounded_int(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _self_test():
    sample = {
        "kind": "request_metadata", "request_seq": 7, "time_utc_ms": 1_800_000_000_000,
        "origin": {"scheme": "https", "host": "api.trae.cn", "port": 443},
        "path_sha256": "a" * 64,
        "path_segments": [{"kind": "static", "index": 1, "value": "api"},
                          {"kind": "hash", "index": 4, "sha256": "b" * 64}],
        "method": "POST", "configured_header_names": ["authorization", "content-type"],
        "header_names_status": "read", "body_read": False, "response_read": False,
    }
    safe = sanitize(sample)
    assert safe is not None and safe["configured_header_names"] == ["authorization", "content-type"]
    assert sanitize(dict(sample, body_read=True)) is None
    assert sanitize(dict(sample, origin={"scheme": "https", "host": "evil.example", "port": 443})) is None
    assert sanitize(dict(sample, configured_header_names=["authorization: bearer secret"])) is None
    assert sanitize(dict(sample, url="https://api.trae.cn/private?token=secret")) == safe
    other = sanitize({"kind": "other_origin", "request_seq": 8,
                      "origin": {"scheme": "https", "host": "public.example", "port": 443},
                      "origin_status": "public", "path_read": False, "headers_read": False,
                      "method": "POST",
                      "path": "/must-not-print", "header_values": ["secret"]})
    assert other is not None and "path" not in other and "header_values" not in other
    assert sanitize({"kind": "other_origin", "request_seq": 8, "origin": None,
                     "origin_status": "hidden", "method": "unknown",
                     "path_read": False, "headers_read": False}) is not None
    ready = sanitize({
        "kind": "observer_ready", "observe_seconds": 300, "hook_count": 2,
        "body_api_ready": False, "process_image_path_match": True,
        "process_image_sha256_match": True, "module_path_match": True,
        "module_sha256_match": True, "process_type_match": True, "parent_pid_match": True,
        "method_getter_ready": True, "header_getters_ready": True,
        "created_local": DEFAULT_CREATED,
    })
    assert ready is not None and ready["scope"] == "url_origin_path_method_header_names_only"
    assert sanitize(dict({
        "kind": "observer_ready", "observe_seconds": 300, "hook_count": 2,
        "body_api_ready": False, "process_image_path_match": True,
        "process_image_sha256_match": True, "module_path_match": True,
        "module_sha256_match": True, "process_type_match": True, "parent_pid_match": True,
        "method_getter_ready": False, "header_getters_ready": True,
        "created_local": DEFAULT_CREATED,
    })) is None
    assert sanitize(dict({"kind": "coverage_summary", "coverage": {key: 0 for key in COVERAGE_KEYS}},
                         extra="raw-secret")) is not None
    segments_sample = dict(sample, path_segments=[
        {"kind": "static", "index": 1, "value": "api"},
        {"kind": "hash", "index": 2, "sha256": "b" * 64},
    ])
    assert sanitize(segments_sample) is not None
    assert sanitize(dict(sample, path_segments=[{"kind": "static", "index": 4, "value": "short-user-id"}])) is None
    assert _parse_local_created("2026-10-27T09:33:35.1079130+08:00") == _parse_local_created(DEFAULT_CREATED)
    try:
        _parse_local_created("2026-10-27T09:33:35.10791301+08:00")
        raise AssertionError("timestamp precision above PowerShell round-trip format must fail")
    except ValueError:
        pass
    encoded = json.dumps({"safe": safe, "other": other, "ready": ready}, separators=(",", ":"))
    for forbidden in ("must-not-print", "bearer secret", "token=secret", "header_values"):
        assert forbidden not in encoded
    print(json.dumps({"self_test": "passed", "cases": 11}, separators=(",", ":")))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Passive, metadata-only Cronet observer")
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
    parser.add_argument("--run-id", help="unique output subdirectory under ignored logs/")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not 1 <= args.seconds <= MAX_OBSERVE_SECONDS:
        print(json.dumps({"kind": "preflight_rejected", "reason": "seconds_out_of_range"}), flush=True)
        return 2
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.image_sha256) or not re.fullmatch(r"[0-9a-fA-F]{64}", args.module_sha256):
        print(json.dumps({"kind": "preflight_rejected", "reason": "hash_format"}), flush=True)
        return 2
    if not isinstance(args.run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.run_id):
        print(json.dumps({"kind": "preflight_rejected", "reason": "invalid_run_id"}), flush=True)
        return 2
    output_path = _output_path_for_run(args.run_id)
    try:
        identity = _identity_preflight(args)
    except Exception as exc:
        record = _error_record(exc, "preflight", "identity_gate_failed")
        print(json.dumps({
            "kind": "preflight_rejected", "phase": record["phase"],
            "error_type": record["error_type"], "reason": record["reason"],
        }, separators=(",", ":")), flush=True)
        return 2
    try:
        import frida
    except Exception as exc:
        record = _error_record(exc, "preflight", "frida_unavailable")
        print(json.dumps({
            "kind": "preflight_rejected", "phase": record["phase"],
            "error_type": record["error_type"], "reason": record["reason"],
        }, separators=(",", ":")), flush=True)
        return 2
    try:
        output = _create_output_file(output_path)
    except FileExistsError:
        print(json.dumps({
            "kind": "preflight_rejected", "phase": "output",
            "error_type": "FileExistsError", "reason": "output_exists",
        }, separators=(",", ":")), flush=True)
        return 2
    except Exception as exc:
        record = _error_record(exc, "output", "output_create_failed")
        print(json.dumps({
            "kind": "preflight_rejected", "phase": record["phase"],
            "error_type": record["error_type"], "reason": record["reason"],
        }, separators=(",", ":")), flush=True)
        return 2

    lock = threading.Lock()
    state = {"hook_install": None, "ready": False, "coverage": None}
    installed_event = threading.Event()
    detached_event = threading.Event()
    active = []
    counters = {"events_written": 0, "bytes_written": 0, "events_dropped": 0}
    output_closed = {"value": False}
    output_failed = {"value": False}
    stdout_failed = {"value": False}
    output_error_reported = {"value": False}
    exit_code = 0
    expected_path = _path_key(args.module_path)

    def report_output_error(exc):
        if output_error_reported["value"]:
            return
        output_error_reported["value"] = True
        try:
            record = _error_record(exc, "output", "output_failed")
            safe = sanitize(record, target_pid=args.pid)
            if safe is not None:
                print(json.dumps(safe, ensure_ascii=True, separators=(",", ":")),
                      file=sys.stderr, flush=True)
        except BaseException:
            pass

    def emit(payload, critical=False):
        try:
            safe = sanitize(payload, target_pid=args.pid)
            if safe is None:
                counters["events_dropped"] += 1
                return False
            line = json.dumps(safe, ensure_ascii=True, separators=(",", ":"))
            encoded_size = len((line + "\n").encode("utf-8"))
            with lock:
                if output_closed["value"] or output_failed["value"]:
                    counters["events_dropped"] += 1
                    return False
                if encoded_size > MAX_LINE_BYTES or counters["events_written"] >= MAX_EVENTS + 16:
                    counters["events_dropped"] += 1
                    return False
                limit = MAX_OUTPUT_BYTES if critical else MAX_OUTPUT_BYTES - RESERVED_OUTPUT_BYTES
                if counters["bytes_written"] + encoded_size > limit:
                    counters["events_dropped"] += 1
                    return False
                try:
                    output.write(line + "\n")
                    output.flush()
                except Exception as exc:
                    output_failed["value"] = True
                    counters["events_dropped"] += 1
                    report_output_error(exc)
                    return False
                counters["events_written"] += 1
                counters["bytes_written"] += encoded_size
                if not stdout_failed["value"]:
                    try:
                        print(line, flush=True)
                    except Exception as exc:
                        stdout_failed["value"] = True
                        report_output_error(exc)
                # The file is authoritative. A broken console must not make a
                # durable ready record claim that the observer did not start.
            return True
        except BaseException:
            # A reporting failure must never interrupt the outer detach/close path.
            output_failed["value"] = True
            try:
                counters["events_dropped"] += 1
            except BaseException:
                pass
            return False

    def on_message(message, _data):
        if message.get("type") == "send":
            payload = message.get("payload")
            emit(payload, critical=isinstance(payload, dict) and payload.get("kind") in {
                "hook_install", "coverage_summary", "observer_timeout"
            })
            if isinstance(payload, dict) and payload.get("kind") == "hook_install":
                state["hook_install"] = sanitize(payload, target_pid=args.pid)
                installed_event.set()
            elif isinstance(payload, dict) and payload.get("kind") == "coverage_summary":
                safe = sanitize(payload, target_pid=args.pid)
                state["coverage"] = safe.get("coverage") if safe else None
        elif message.get("type") == "error":
            emit({"kind": "observer_error", "phase": "script",
                  "error_type": "ScriptError", "reason": "script_failed"}, critical=True)

    try:
        phase = "attach"
        device = frida.get_local_device()
        session = device.attach(args.pid)
        item = {"session": session, "script": None}
        active.append(item)

        def on_detached(*_args):
            detached_event.set()
            emit({"kind": "target_detached"}, critical=True)

        session.on("detached", on_detached)
        phase = "identity"
        attached_identity = _identity_preflight(args)
        if attached_identity != identity:
            raise RuntimeError("process_identity_changed")
        config = {
            "pid": args.pid, "expected_module_path": str(args.module_path),
            "max_seconds": args.seconds,
        }
        phase = "script"
        source = AGENT_PATH.read_text(encoding="utf-8")
        source += "\nNativeMetadataObserver.install(" + json.dumps(config, ensure_ascii=True) + ");\n"
        script = session.create_script(source, runtime="qjs")
        item["script"] = script
        script.on("message", on_message)
        script.load()
        phase = "readiness"
        if not installed_event.wait(10):
            raise RuntimeError("hook_install_timeout")
        install = state["hook_install"] or {}
        if (
            install.get("hook_count") != 2
            or set(install.get("hooks", [])) != HOOKS
            or install.get("missing") != []
            or install.get("module_path_match") is not True
            or install.get("method_getter_ready") is not True
            or install.get("header_getters_ready") is not True
            or install.get("body_api_ready") is not False
        ):
            raise RuntimeError("metadata_readiness_rejected")
        ready = {
            "kind": "observer_ready", "observe_seconds": args.seconds,
            "hook_count": 2, "body_api_ready": False,
            "method_getter_ready": install.get("method_getter_ready") is True,
            "header_getters_ready": install.get("header_getters_ready") is True,
            "created_local": identity["created_local"],
            "process_image_path_match": True, "process_image_sha256_match": True,
            "module_path_match": True, "module_sha256_match": True,
            "process_type_match": True, "parent_pid_match": True,
        }
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
        fallback = {
            "attach": "attach_failed", "identity": "process_identity_changed",
            "script": "script_failed", "readiness": "metadata_readiness_rejected",
            "observe": "observer_failed",
        }.get(locals().get("phase", "observe"), "observer_failed")
        emit(_error_record(exc, locals().get("phase", "observe"), fallback), critical=True)
    finally:
        cleanup_ok = True
        for item in reversed(active):
            if item["script"] is not None:
                try:
                    item["script"].unload()
                    emit({"kind": "script_unloaded"}, critical=True)
                except Exception as exc:
                    cleanup_ok = False
                    exit_code = 1
                    emit(_error_record(exc, "unload", "cleanup_failed"), critical=True)
                finally:
                    try:
                        item["session"].detach()
                        emit({"kind": "session_detached"}, critical=True)
                    except Exception as exc:
                        cleanup_ok = False
                        exit_code = 1
                        emit(_error_record(exc, "detach", "cleanup_failed"), critical=True)
            else:
                try:
                    item["session"].detach()
                    emit({"kind": "session_detached"}, critical=True)
                except Exception as exc:
                    cleanup_ok = False
                    exit_code = 1
                    emit(_error_record(exc, "detach", "cleanup_failed"), critical=True)
        try:
            final_identity = _powershell_identity(args.pid)
            final_created = _parse_local_created(final_identity["created_local"])
            initial_created = _parse_local_created(identity["created_local"])
            same_identity = (
                final_identity.get("pid") == args.pid
                and final_identity.get("parent_pid") == args.parent_pid
                and abs((final_created - initial_created).total_seconds()) <= 1.0
                and _path_key(final_identity.get("image_path", "")) == _path_key(args.image_path)
                and _path_key(final_identity.get("module_path", "")) == expected_path
                and final_identity.get("process_type") == DEFAULT_PROCESS_TYPE
                and final_identity.get("utility_subtype") == DEFAULT_UTILITY_SUBTYPE
                and _file_sha256(Path(final_identity["image_path"])) == args.image_sha256.upper()
                and _file_sha256(Path(final_identity["module_path"])) == args.module_sha256.upper()
            )
        except Exception:
            same_identity = False
        try:
            emit({"kind": "process_check", "same_identity": same_identity}, critical=True)
            if not same_identity:
                exit_code = 1
            if not active:
                emit({"kind": "no_session_attached"}, critical=True)
            elif cleanup_ok:
                emit({"kind": "cleanup_complete"}, critical=True)
            else:
                emit({"kind": "cleanup_incomplete"}, critical=True)
            emit({
                "kind": "output_summary", "events_before_summary": counters["events_written"],
                "bytes_before_summary": counters["bytes_written"],
                "events_dropped": counters["events_dropped"], "cleanup_ok": cleanup_ok,
                "output_ok": not output_failed["value"] and not stdout_failed["value"],
                "output_ref": output_path.relative_to(ROOT).as_posix(),
            }, critical=True)
        finally:
            output_closed["value"] = True
            try:
                output.close()
            except Exception:
                output_failed["value"] = True
                exit_code = 1
        if output_failed["value"] or stdout_failed["value"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
