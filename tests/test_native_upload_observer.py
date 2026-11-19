"""Offline sanitizer and private-digest tests for the native upload observer."""
from __future__ import annotations

import json
import contextlib
import copy
import io
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import native_upload_observer as observer


def projection(marker_hit: bool = True) -> dict:
    result = {
        "parse_state": "json",
        "body_bytes": 128,
        "marker_hit": marker_hit,
        "marker_semantics": "unverified",
        "marker_paths": ([[{"kind": "key", "value": "data"},
                            {"kind": "key", "value": "query"},
                            {"kind": "key", "value": "model_name"}]] if marker_hit else []),
        "schema": [
            {"path": [{"kind": "key", "value": "data"}], "type": "object", "top_level": True},
            {"path": [{"kind": "key", "value": "model_name"}], "type": "string", "top_level": True},
        ],
        "model_fields": [{"path": [{"kind": "key", "value": "model_name"}],
                          "value_state": "target"}],
        "enum_fields": [
            {"path": [{"kind": "key", "value": "function"}], "value": "chat"},
            {"path": [{"kind": "key", "value": "agent_type"}], "value": "builder"},
            {"path": [{"kind": "key", "value": "scene_location"}], "value": 2},
        ],
        "id_hashes": [{"path": [{"kind": "key", "value": "session_id"}], "sha256": "a" * 64}],
        "usage": [{"path": [{"kind": "key", "value": "prompt_tokens"}], "value": 12}],
    }
    return result


def upload_event(route: str = "/api/agent/v3/llm_utils_chat", marker_hit: bool = True) -> dict:
    info = observer.ROUTES[route]
    return {
        "kind": "upload_projection",
        "request_seq": 7,
        "route_name": info["route_name"],
        "route": route,
        "route_sha256": info["path_sha256"],
        "time_utc_ms": 1_798_000_000_000,
        "projection": projection(marker_hit),
    }


class NativeUploadObserverTests(unittest.TestCase):
    def test_sanitizes_bounded_projection(self) -> None:
        safe = observer.sanitize(upload_event())
        self.assertIsNotNone(safe)
        self.assertEqual(safe["projection"]["marker_semantics"], "unverified")
        self.assertEqual(safe["route_name"], "llm_utils_chat")

    def test_sparse_non_json_projection_matches_js_core_contract(self) -> None:
        for parse_state in ("invalid_json", "invalid_utf8", "bounded_unknown", "invalid_buffer"):
            event = upload_event()
            event["projection"] = {
                "parse_state": parse_state, "body_bytes": 128,
                "marker_hit": False, "marker_semantics": "unverified", "marker_paths": [],
            }
            safe = observer.sanitize(event)
            self.assertIsNotNone(safe, parse_state)
            self.assertEqual(safe["projection"]["parse_state"], parse_state)
            self.assertEqual(safe["projection"]["schema"], [])
            self.assertEqual(safe["projection"]["id_hashes"], [])

        event = upload_event()
        event["projection"] = {
            "parse_state": "invalid_json", "body_bytes": 128,
            "marker_hit": False, "marker_semantics": "unverified", "marker_paths": [],
            "schema": [],
        }
        self.assertIsNone(observer.sanitize(event))

    def test_python_path_allowlist_accepts_all_js_static_projection_keys(self) -> None:
        for key in ("assistant", "model_config_name", "system", "user", "x"):
            event = upload_event()
            event["projection"]["schema"].append({
                "path": [{"kind": "key", "value": key}],
                "type": "string", "top_level": True,
            })
            self.assertIsNotNone(observer.sanitize(event), key)

    def test_projection_rejection_diagnostic_exposes_only_fixed_reason_codes(self) -> None:
        event = upload_event()
        event["projection"]["schema"] = [{
            "path": [{"kind": "key", "value": "user_generated_dynamic_key"}],
            "type": "string", "top_level": True,
        }]
        self.assertIsNone(observer.sanitize(event))
        diagnostic = observer._projection_rejection_event(event)
        self.assertEqual(diagnostic, {
            "kind": "projection_rejected", "request_seq": 7,
            "route_name": "llm_utils_chat", "parse_state": "json", "stage": "path",
        })
        self.assertIsNotNone(observer.sanitize(diagnostic))
        rendered = json.dumps(diagnostic)
        self.assertNotIn("user_generated_dynamic_key", rendered)
        self.assertNotIn("raw_body", rendered)
        line_limit_diagnostic = observer._projection_rejection_event(
            upload_event(), stage_override="line_limit",
        )
        self.assertEqual(line_limit_diagnostic["stage"], "line_limit")
        self.assertIsNotNone(observer.sanitize(line_limit_diagnostic))

        oversized = upload_event()
        oversized["projection"]["schema"] = [{
            "path": [{"kind": "hash", "sha256": "a" * 64}] * observer.MAX_PATH_SEGMENTS,
            "type": "string", "top_level": True,
        } for _ in range(observer.MAX_SCHEMA)]
        safe_oversized = observer.sanitize(oversized)
        self.assertIsNotNone(safe_oversized)
        self.assertGreater(observer._event_line_size(safe_oversized), observer.MAX_LINE_BYTES)
        line_limit_diagnostic = observer._projection_rejection_event(
            oversized, stage_override="line_limit",
        )
        self.assertIsNotNone(observer.sanitize(line_limit_diagnostic))

        sparse = upload_event()
        sparse["projection"] = {
            "parse_state": "invalid_json", "body_bytes": 128,
            "marker_hit": False, "marker_semantics": "unverified", "marker_paths": [],
            "schema": [],
        }
        self.assertEqual(observer._projection_rejection_stage(sparse["projection"]), "non_json_shape")
        diagnostic = observer._projection_rejection_event(sparse)
        self.assertEqual(diagnostic["parse_state"], "invalid_json")
        self.assertEqual(diagnostic["stage"], "non_json_shape")

        invalid_route = dict(event, route="/api/agent/v3/not-reviewed")
        self.assertIsNone(observer._projection_rejection_event(invalid_route))

    def test_rejects_raw_fields_unknown_routes_and_dynamic_key_names(self) -> None:
        event = upload_event()
        self.assertIsNone(observer.sanitize(dict(event, raw_body="synthetic-secret")))
        self.assertIsNone(observer.sanitize(dict(event, route="/api/agent/v3/not-reviewed")))
        bad_projection = dict(event["projection"], schema=[{
            "path": [{"kind": "key", "value": "user_generated_dynamic_key"}],
            "type": "string", "top_level": True,
        }])
        self.assertIsNone(observer.sanitize(dict(event, projection=bad_projection)))

    def test_marker_false_can_export_only_safe_structure_as_unverified(self) -> None:
        safe = observer.sanitize(upload_event(marker_hit=False))
        self.assertIsNotNone(safe)
        self.assertFalse(safe["projection"]["marker_hit"])
        self.assertEqual(safe["projection"]["marker_semantics"], "unverified")
        self.assertEqual(safe["projection"]["schema"][0]["type"], "object")
        self.assertEqual(safe["projection"]["id_hashes"][0]["sha256"], "a" * 64)
        self.assertEqual(safe["projection"]["enum_fields"][-1]["value"], 2)
        invalid = upload_event(marker_hit=False)
        invalid["projection"]["schema"] = [{
            "path": [{"kind": "key", "value": "user_generated_dynamic_key"}],
            "type": "string", "top_level": True,
        }]
        self.assertIsNone(observer.sanitize(invalid))

    def test_enum_projection_uses_field_specific_finite_allowlists(self) -> None:
        event = upload_event()
        self.assertIsNotNone(observer.sanitize(event))
        event["projection"]["enum_fields"].append({
            "path": [{"kind": "key", "value": "function_name"}], "value": "run_command",
        })
        self.assertIsNone(observer.sanitize(event))
        event = upload_event()
        event["projection"]["enum_fields"][0]["value"] = "unseen_function_value"
        self.assertIsNone(observer.sanitize(event))
        event = upload_event()
        event["projection"]["enum_fields"][-1]["value"] = 2.0
        self.assertIsNone(observer.sanitize(event))

    def test_private_digest_is_consumed_and_never_projected(self) -> None:
        class FakeInventory:
            def __init__(self) -> None:
                self.seen = None

            def match_token_digest(self, digest_hex, prefix_kind, header_name):
                self.seen = (digest_hex, prefix_kind, header_name)

                class Result:
                    matched_sources = ("proxy.token",)
                    same_value = True
                    reason = "matched"

                return Result()

        inventory = FakeInventory()
        digest = "a" * 64
        private = {
            "kind": "native_auth_digest", "request_seq": 9,
            "header_name": "authorization", "header_prefix_kind": "cloud_ide_jwt",
            "header_digest_sha256": digest,
        }
        safe = observer._consume_auth_digest(private, inventory)
        self.assertEqual(inventory.seen, (digest, "cloud_ide_jwt", "authorization"))
        self.assertEqual(safe["matched_sources"], ["proxy.token"])
        self.assertEqual(private, {})
        serialized = json.dumps(safe)
        self.assertNotIn(digest, serialized)
        self.assertNotIn("header_digest_sha256", serialized)

    def test_malformed_private_digest_is_cleared(self) -> None:
        private = {
            "kind": "native_auth_digest", "request_seq": 9,
            "header_name": "authorization", "header_prefix_kind": "none",
            "header_digest_sha256": "not-a-digest", "header_value": "never-output",
        }
        self.assertIsNone(observer._consume_auth_digest(private, object()))
        self.assertEqual(private, {})

    def test_callback_attached_descriptor_requires_preflight_exec_rva(self) -> None:
        module_hash = "C" * 64
        modules = {"aha_net.dll": {
            "sha256": module_hash,
            "memory_size": 0x10000,
            "exec_ranges": [(0x1000, 0x1800)],
        }}
        candidate = {
            "kind": "callback_attached", "attached": True, "role": "read",
            "module_name": "AHA_NET.DLL", "module_sha256": module_hash.lower(), "rva": 0x1234,
        }
        safe = observer._candidate_approval(candidate, modules)
        self.assertIsNotNone(safe)
        self.assertEqual(safe["module_name"], "aha_net.dll")
        self.assertNotIn("rva", safe)
        self.assertIsNone(observer._candidate_approval(dict(candidate, rva=0x9000), modules))
        self.assertIsNone(observer._candidate_approval(dict(candidate, rva="0x1234"), modules))
        self.assertIsNone(observer._candidate_approval(dict(candidate, rva=True), modules))
        self.assertIsNone(observer._candidate_approval(dict(candidate, module_name="unknown.dll"), modules))

    def test_route_cap_counts_each_sequence_once(self) -> None:
        state = {
            "route_sequences": {route: set() for route in observer.ROUTES},
            "sequence_route": {}, "route_overflow": set(),
        }
        seq = 1
        routes = list(observer.ROUTES)
        for route in routes:
            for _ in range(16):
                self.assertTrue(observer._admit_route_sequence(state, route, seq))
                self.assertTrue(observer._admit_route_sequence(state, route, seq))
                seq += 1
        self.assertFalse(observer._admit_route_sequence(state, routes[0], seq))
        self.assertFalse(observer._admit_route_sequence(state, routes[1], 1))

    def test_hook_install_requires_all_upload_hooks_and_no_response_hooks(self) -> None:
        hooks = sorted({
            "Cronet_UrlRequest_InitWithParams", "Cronet_UrlRequest_Start",
            "Cronet_UploadDataProvider_CreateWith", "Cronet_UploadDataProvider_GetLength",
            "Cronet_UploadDataProvider_Read", "Cronet_UploadDataProvider_Rewind",
            "Cronet_UploadDataProvider_Close", "Cronet_UploadDataSink_OnReadSucceeded",
            "Cronet_UploadDataSink_OnReadError", "Cronet_UploadDataSink_OnRewindError",
        })
        event = {
            "kind": "hook_install", "pid": observer.DEFAULT_PID, "hook_count": 10,
            "hooks": hooks, "missing": [], "module_name": "sscronet.dll",
            "module_path_match": True, "module_size_match": True,
            "module_sha256_preflight": True, "method_getter_ready": True,
            "header_getters_ready": True, "upload_api_ready": True,
            "response_api_ready": False, "callback_manifest_count": 4,
        }
        self.assertIsNotNone(observer.sanitize(event))
        self.assertIsNone(observer.sanitize(dict(event, missing=["Cronet_UploadDataProvider_Read"])))
        self.assertIsNone(observer.sanitize(dict(event, response_api_ready=True)))

    def test_main_writer_persists_large_real_js_projection(self) -> None:
        node = shutil_which("node")
        if node is None:
            self.skipTest("node is unavailable")
        script_path = ROOT / "tests" / "test_native_upload_observer.js"
        result = subprocess.run(
            [node, str(script_path), "--fixture-events"],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[:200])
        events = json.loads(result.stdout)
        install = copy.deepcopy(next(event for event in events if event.get("kind") == "hook_install"))
        projections = [event for event in events if event.get("kind") == "upload_projection"]
        self.assertGreaterEqual(len(projections), 2)
        large_projection = max(projections, key=observer._event_line_size)
        safe_large = observer.sanitize(large_projection, target_pid=777)
        self.assertIsNotNone(safe_large)
        self.assertGreater(observer._event_line_size(safe_large), 32 * 1024)
        self.assertLessEqual(observer._event_line_size(safe_large), observer.MAX_LINE_BYTES)

        # Include a deliberately rejected path and value sentinel. The live
        # writer must retain only its fixed-label diagnostic, never either value.
        rejected = copy.deepcopy(large_projection)
        rejected["request_seq"] = 999_999
        rejected["projection"]["schema"] = [{
            "path": [{"kind": "key", "value": "private_dynamic_key_sentinel"}],
            "type": "string", "top_level": True,
        }]
        rejected["projection"]["private_value_sentinel"] = "raw_body_secret_sentinel"

        install["pid"] = observer.DEFAULT_PID
        identity = {
            "pid": observer.DEFAULT_PID,
            "parent_pid": observer.DEFAULT_PARENT_PID,
            "created_local": observer.DEFAULT_CREATED,
            "image_path": str(observer.DEFAULT_IMAGE_PATH),
            "process_type": observer.DEFAULT_PROCESS_TYPE,
            "utility_subtype": observer.DEFAULT_UTILITY_SUBTYPE,
            "module_path": str(observer.DEFAULT_MODULE_PATH),
        }
        modules = {
            "trae cn.exe": {
                "name": "trae cn.exe", "path": str(observer.DEFAULT_IMAGE_PATH),
                "sha256": observer.DEFAULT_IMAGE_SHA256, "memory_size": 0x200000,
                "file_size": 1, "exec_ranges": [(0x1000, 0x2000)],
            },
            "sscronet.dll": {
                "name": "sscronet.dll", "path": str(observer.DEFAULT_MODULE_PATH),
                "sha256": observer.DEFAULT_MODULE_SHA256, "memory_size": 0x100000,
                "file_size": 1, "exec_ranges": [(0x1000, 0x2000)],
            },
        }

        class FakeScript:
            def __init__(self) -> None:
                self.message_callback = None

            def on(self, name, callback) -> None:
                if name == "message":
                    self.message_callback = callback

            def load(self) -> None:
                for event in (install, large_projection, rejected):
                    self.message_callback({"type": "send", "payload": copy.deepcopy(event)}, None)

            def unload(self) -> None:
                return None

        class FakeSession:
            def __init__(self) -> None:
                self.detach_callback = None
                self.script = FakeScript()

            def on(self, name, callback) -> None:
                if name == "detached":
                    self.detach_callback = callback

            def create_script(self, _source, runtime=None):
                self.runtime = runtime
                return self.script

            def detach(self) -> None:
                if self.detach_callback is not None:
                    self.detach_callback()

        class FakeDevice:
            def __init__(self) -> None:
                self.session = FakeSession()

            def attach(self, _pid):
                return self.session

        device = FakeDevice()
        fake_frida = types.ModuleType("frida")
        fake_frida.get_local_device = lambda: device
        with tempfile.TemporaryDirectory() as temporary:
            output_base = Path(temporary)
            with patch.object(observer, "OUTPUT_BASE", output_base), \
                    patch.object(observer, "EXPECTED_PYTHON", Path(sys.executable)), \
                    patch.object(observer.metadata_driver, "_identity_preflight", return_value=identity), \
                    patch.object(observer, "_callback_module_snapshot", return_value=modules), \
                    patch.dict(sys.modules, {"frida": fake_frida}), \
                    contextlib.redirect_stdout(io.StringIO()):
                exit_code = observer.main([
                    "--observe-once", "--seconds", "1", "--run-id", "writer-regression",
                ])

            self.assertEqual(exit_code, 0)
            capture_path = output_base / "writer-regression" / "capture.jsonl"
            records = [json.loads(line) for line in capture_path.read_text(encoding="utf-8").splitlines()]
            written_projection = next(
                record for record in records
                if record.get("kind") == "upload_projection" and
                record.get("request_seq") == large_projection["request_seq"]
            )
            written_line = json.dumps(written_projection, ensure_ascii=True, separators=(",", ":")) + "\n"
            self.assertGreater(len(written_line.encode("utf-8")), 32 * 1024)
            self.assertLessEqual(len(written_line.encode("utf-8")), observer.MAX_LINE_BYTES)
            diagnostics = [record for record in records if record.get("kind") == "projection_rejected"]
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(diagnostics[0]["stage"], "projection_shape")
            summary = next(record for record in records if record.get("kind") == "output_summary")
            self.assertEqual(summary["events_dropped"], 1)
            self.assertTrue(summary["cleanup_ok"])
            serialized = capture_path.read_text(encoding="utf-8")
            self.assertNotIn("private_dynamic_key_sentinel", serialized)
            self.assertNotIn("raw_body_secret_sentinel", serialized)
            self.assertNotIn("TRAE_NATIVE_20261027_B_OK", serialized)

    def test_node_public_fixture_round_trips_through_real_sanitizer(self) -> None:
        node = shutil_which("node")
        if node is None:
            self.skipTest("node is unavailable")
        script = ROOT / "tests" / "test_native_upload_observer.js"
        if not script.is_file():
            self.skipTest("JS hook fixture is not ready yet")
        result = subprocess.run(
            [node, str(script), "--fixture-events"],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[:200])
        events = json.loads(result.stdout)
        self.assertIsInstance(events, list)
        self.assertGreaterEqual(len(events), 2)
        callback_modules = {"agent_callbacks.dll": {
            "sha256": "B" * 64,
            "memory_size": 0x1000,
            "exec_ranges": [(0x100, 0x200)],
        }}
        safe = [
            (observer._candidate_approval(event, callback_modules)
             if event.get("kind") == "callback_attached"
             else observer.sanitize(event, target_pid=777))
            for event in events
        ]
        self.assertTrue(all(event is not None for event in safe))
        kinds = {event["kind"] for event in safe}
        self.assertIn("hook_install", kinds)
        self.assertIn("upload_projection", kinds)
        projection_events = [event for event in safe if event["kind"] == "upload_projection"]
        self.assertGreaterEqual(len(projection_events), 2)
        install_event = next(event for event in events if event.get("kind") == "hook_install")
        ready = observer._ready_event_from_install(
            install_event, "2026-10-27T22:00:00+08:00", 300, True, target_pid=777,
        )
        self.assertIsNotNone(ready)
        self.assertEqual(ready["module_sha256_match"], install_event["module_sha256_preflight"])
        self.assertIsNotNone(observer.sanitize(ready, target_pid=777))

        callback_events = [event for event in events if event.get("kind") == "callback_attached"]
        self.assertGreater(len(callback_events), 0)
        for approved in (event for event in safe if event["kind"] == "callback_hook"):
            self.assertNotIn("rva", approved)
        schema_keys = {
            segment["value"]
            for event in projection_events
            for field in event["projection"]["schema"]
            for segment in field["path"]
            if segment.get("kind") == "key"
        }
        self.assertTrue({"assistant", "model_config_name", "system", "user", "x"}.issubset(schema_keys))
        line_sizes = [observer._event_line_size(event) for event in projection_events]
        rendered = json.dumps(safe)
        self.assertNotIn("TRAE_NATIVE_20261027_B_OK", rendered)
        self.assertNotIn("raw_body", rendered)
        self.assertLessEqual(observer.MAX_LINE_BYTES, 128 * 1024)
        self.assertTrue(any(size > 32 * 1024 for size in line_sizes))
        self.assertTrue(all(size <= observer.MAX_LINE_BYTES for size in line_sizes))


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


if __name__ == "__main__":
    unittest.main()
