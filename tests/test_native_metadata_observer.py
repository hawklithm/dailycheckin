"""Offline tests for the passive native metadata observer and sanitizer."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import native_metadata_observer as observer  # noqa: E402


class NativeMetadataObserverTests(unittest.TestCase):
    def test_python_self_test(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(observer._self_test(), 0)
        self.assertEqual(json.loads(output.getvalue()), {"self_test": "passed", "cases": 11})

    def test_known_route_projection_drops_unapproved_fields(self):
        payload = {
            "kind": "request_metadata", "request_seq": 2, "time_utc_ms": 1_800_000_000_000,
            "origin": {"scheme": "https", "host": "api.trae.cn", "port": 443},
            "path_sha256": "a" * 64,
            "path_segments": [
                {"kind": "static", "index": 1, "value": "api"},
                {"kind": "hash", "index": 5, "sha256": "b" * 64},
            ],
            "method": "POST", "configured_header_names": ["content-type", "authorization"],
            "header_names_status": "read", "body_read": False, "response_read": False,
            "raw_url": "https://api.trae.cn/api/private?token=DO_NOT_EMIT",
            "header_values": ["DO_NOT_EMIT"],
        }
        safe = observer.sanitize(payload)
        self.assertIsNotNone(safe)
        encoded = json.dumps(safe)
        self.assertNotIn("raw_url", encoded)
        self.assertNotIn("DO_NOT_EMIT", encoded)
        self.assertEqual(safe["configured_header_names"], ["authorization", "content-type"])

    def test_unknown_origin_has_no_path_or_header_metadata(self):
        safe = observer.sanitize({
            "kind": "other_origin", "request_seq": 4,
            "origin": {"scheme": "https", "host": "public.example", "port": 443},
            "origin_status": "public", "method": "POST",
            "path_read": False, "headers_read": False,
            "raw_path": "/private/segment", "header_values": ["secret"],
        })
        self.assertIsNotNone(safe)
        self.assertEqual(safe["method"], "POST")
        self.assertNotIn("raw_path", safe)
        self.assertNotIn("header_values", safe)

    def test_readiness_requires_typed_metadata_getters(self):
        ready = {
            "kind": "observer_ready", "observe_seconds": 90, "hook_count": 2,
            "body_api_ready": False, "method_getter_ready": True,
            "header_getters_ready": True, "process_image_path_match": True,
            "process_image_sha256_match": True, "module_path_match": True,
            "module_sha256_match": True, "process_type_match": True,
            "parent_pid_match": True, "created_local": observer.DEFAULT_CREATED,
        }
        self.assertIsNotNone(observer.sanitize(ready))
        self.assertIsNone(observer.sanitize(dict(ready, header_getters_ready=False)))
        self.assertIsNone(observer.sanitize(dict(ready, method_getter_ready=False)))

    def test_run_output_is_unique_and_conflicts_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "logs" / "observer"
            first = observer._output_path_for_run("run_one", base)
            second = observer._output_path_for_run("run_two", base)
            self.assertNotEqual(first, second)
            with observer._create_output_file(first) as output:
                output.write("safe\n")
            with observer._create_output_file(second) as output:
                output.write("safe\n")
            with self.assertRaises(FileExistsError):
                observer._create_output_file(first)
            with self.assertRaises(ValueError):
                observer._output_path_for_run("../escape", base)

    def test_error_projection_uses_only_allowlisted_type_and_reason(self):
        record = observer._error_record(
            PermissionError("secret-bearing raw error text"), "attach", "attach_failed"
        )
        safe = observer.sanitize(record)
        self.assertEqual(safe, {
            "kind": "observer_error", "pid": observer.DEFAULT_PID,
            "phase": "attach", "error_type": "PermissionError",
            "reason": "attach_failed",
        })
        self.assertNotIn("secret-bearing", json.dumps(safe))

    def test_powershell_roundtrip_timestamp_accepts_seven_fraction_digits(self):
        six_digits = observer._parse_local_created(observer.DEFAULT_CREATED)
        seven_digits = observer._parse_local_created("2026-10-27T09:33:35.1079130+08:00")
        self.assertEqual(six_digits, seven_digits)
        with self.assertRaises(ValueError):
            observer._parse_local_created("2026-10-27T09:33:35.10791301+08:00")

    def test_attach_identity_is_rechecked_before_script_load(self):
        class FakeOutput:
            def __init__(self):
                self.closed = False
                self.lines = []

            def write(self, value):
                self.lines.append(value)
                return len(value)

            def flush(self):
                pass

            def close(self):
                self.closed = True

        class FakeSession:
            def __init__(self):
                self.detached = False
                self.created_script = False

            def on(self, *_args):
                pass

            def create_script(self, *_args, **_kwargs):
                self.created_script = True
                raise AssertionError("identity mismatch must stop before script creation")

            def detach(self):
                self.detached = True

        class FakeDevice:
            def __init__(self, session):
                self.session = session

            def attach(self, _pid):
                return self.session

        identity = {
            "pid": observer.DEFAULT_PID, "parent_pid": observer.DEFAULT_PARENT_PID,
            "created_local": observer.DEFAULT_CREATED,
            "image_path": str(observer.DEFAULT_IMAGE_PATH),
            "module_path": str(observer.DEFAULT_MODULE_PATH),
            "process_type": observer.DEFAULT_PROCESS_TYPE,
            "utility_subtype": observer.DEFAULT_UTILITY_SUBTYPE,
        }
        changed = dict(identity, parent_pid=observer.DEFAULT_PARENT_PID + 1)
        session = FakeSession()
        output = FakeOutput()
        fake_frida = types.SimpleNamespace(get_local_device=lambda: FakeDevice(session))
        with mock.patch.object(observer, "_identity_preflight", side_effect=[identity, changed]), \
             mock.patch.object(observer, "_powershell_identity", return_value=identity), \
             mock.patch.object(observer, "_file_sha256", return_value=observer.DEFAULT_IMAGE_SHA256), \
             mock.patch.object(observer, "_create_output_file", return_value=output), \
             mock.patch.dict(sys.modules, {"frida": fake_frida}), \
             contextlib.redirect_stdout(io.StringIO()):
            code = observer.main([
                "--observe-once", "--pid", str(observer.DEFAULT_PID),
                "--seconds", "1", "--run-id", "identity-race-test",
            ])
        self.assertEqual(code, 1)
        self.assertFalse(session.created_script)
        self.assertTrue(session.detached)
        self.assertTrue(output.closed)
        written = "".join(output.lines)
        self.assertIn('"reason":"process_identity_changed"', written)
        self.assertNotIn("parent_pid", written)

    def test_output_failure_still_unloads_detaches_and_closes(self):
        class BrokenOutput:
            def __init__(self):
                self.closed = False

            def write(self, _value):
                raise OSError("secret-bearing sink error")

            def flush(self):
                pass

            def close(self):
                self.closed = True

        class FakeScript:
            def __init__(self):
                self.callbacks = {}
                self.unloaded = False

            def on(self, name, callback):
                self.callbacks[name] = callback

            def load(self):
                payload = {
                    "kind": "hook_install", "hook_count": 2,
                    "hooks": sorted(observer.HOOKS), "missing": [],
                    "module_name": "sscronet.dll", "module_path_match": True,
                    "method_getter_ready": True, "header_getters_ready": True,
                    "body_api_ready": False,
                }
                self.callbacks["message"]({"type": "send", "payload": payload}, None)

            def unload(self):
                self.unloaded = True

        class FakeSession:
            def __init__(self):
                self.callbacks = {}
                self.script = FakeScript()
                self.detached = False

            def on(self, name, callback):
                self.callbacks[name] = callback

            def create_script(self, *_args, **_kwargs):
                return self.script

            def detach(self):
                self.detached = True

        class FakeDevice:
            def __init__(self, session):
                self.session = session

            def attach(self, _pid):
                return self.session

        identity = {
            "pid": observer.DEFAULT_PID, "parent_pid": observer.DEFAULT_PARENT_PID,
            "created_local": observer.DEFAULT_CREATED,
            "image_path": str(observer.DEFAULT_IMAGE_PATH),
            "module_path": str(observer.DEFAULT_MODULE_PATH),
            "process_type": observer.DEFAULT_PROCESS_TYPE,
            "utility_subtype": observer.DEFAULT_UTILITY_SUBTYPE,
        }
        session = FakeSession()
        output = BrokenOutput()
        fake_frida = types.SimpleNamespace(get_local_device=lambda: FakeDevice(session))
        error_output = io.StringIO()
        with mock.patch.object(observer, "_identity_preflight", return_value=identity), \
             mock.patch.object(observer, "_powershell_identity", return_value=identity), \
             mock.patch.object(observer, "_file_sha256", return_value=observer.DEFAULT_IMAGE_SHA256), \
             mock.patch.object(observer, "_create_output_file", return_value=output), \
             mock.patch.dict(sys.modules, {"frida": fake_frida}), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(error_output):
            code = observer.main([
                "--observe-once", "--pid", str(observer.DEFAULT_PID),
                "--seconds", "1", "--run-id", "sink-failure-test",
            ])
        self.assertEqual(code, 1)
        self.assertTrue(session.script.unloaded)
        self.assertTrue(session.detached)
        self.assertTrue(output.closed)
        self.assertIn('"error_type":"OSError"', error_output.getvalue())
        self.assertIn('"reason":"output_failed"', error_output.getvalue())
        self.assertNotIn("secret-bearing", error_output.getvalue())

    def test_fake_native_pointer_capture_and_query_boundary(self):
        js_path = json.dumps(str(Path(observer.AGENT_PATH).resolve()))
        script = r'''
const assert = require('assert');
const crypto = require('crypto');
const O = require(__JS_PATH__);

class FakeNativePointer {
  constructor(text, shared, base = 0) {
    this.shared = shared || {bytes: Buffer.from(text, 'ascii'), reads: [], maxRead: Infinity, throwAt: -1};
    this.base = base;
  }
  isNull() { return false; }
  add(amount) { return new FakeNativePointer('', this.shared, this.base + amount); }
  readU8() {
    if (this.base === this.shared.throwAt || this.base > this.shared.maxRead) throw new Error('pointer sentinel');
    this.shared.reads.push(this.base);
    return this.shared.bytes[this.base] || 0;
  }
}

function pointer(text, maxRead = Infinity, throwAt = -1) {
  const shared = {bytes: Buffer.from(text + '\0', 'ascii'), reads: [], maxRead, throwAt};
  return {root: new FakeNativePointer('', shared), shared};
}
function readers() {
  return {
    methodReady: true,
    method: () => new FakeNativePointer('POST\0'),
    headersReady: true,
    headersSize: () => 1,
    headersAt: () => ({isNull: () => false}),
    headerName: () => new FakeNativePointer('Content-Type\0')
  };
}

const url = 'https://api.trae.cn/api/ide/v2/new_route/abcdef?query=QUERY_SENTINEL#frag';
const queryAt = url.indexOf('?');
const known = pointer(url, queryAt);
const captured = O.captureInitForTest(known.root, {}, readers());
assert.strictEqual(captured.kind, 'known_origin');
assert.deepStrictEqual(captured.origin, {scheme: 'https', host: 'api.trae.cn', port: 443});
assert.strictEqual(captured.method, 'POST');
assert.deepStrictEqual(captured.headers, {status: 'read', names: ['content-type']});
assert.deepStrictEqual(captured.path_segments.map(x => x.kind), ['static', 'static', 'static', 'hash', 'hash']);
assert.deepStrictEqual(captured.path_segments.slice(0, 3).map(x => x.value), ['api', 'ide', 'v2']);
assert.strictEqual(captured.path_segments[3].sha256,
  crypto.createHash('sha256').update(encodeURIComponent('new_route'), 'ascii').digest('hex'));
assert.strictEqual(captured.path_segments[4].sha256,
  crypto.createHash('sha256').update(encodeURIComponent('abcdef'), 'ascii').digest('hex'));
assert.strictEqual(captured.path_sha256,
  crypto.createHash('sha256').update(encodeURIComponent('/api/ide/v2/new_route/abcdef'), 'ascii').digest('hex'));
assert(Math.max(...known.shared.reads) <= queryAt, 'query bytes must not be read');
assert(!JSON.stringify(captured).includes('QUERY_SENTINEL'));

const noPathUrl = 'https://api.trae.cn?NO_PATH_QUERY_SENTINEL';
const noPath = pointer(noPathUrl, noPathUrl.indexOf('?'));
const noPathResult = O.captureInitForTest(noPath.root, {}, readers());
assert.strictEqual(noPathResult.kind, 'known_origin');
assert.strictEqual(noPathResult.path_sha256,
  crypto.createHash('sha256').update(encodeURIComponent('/'), 'ascii').digest('hex'));
assert(Math.max(...noPath.shared.reads) <= noPathUrl.indexOf('?'));
assert(!JSON.stringify(noPathResult).includes('NO_PATH_QUERY_SENTINEL'));

const otherUrl = 'https://public.example/private/path?OTHER_QUERY_SENTINEL';
const authorityEnd = otherUrl.indexOf('/', otherUrl.indexOf('://') + 3);
const other = pointer(otherUrl, authorityEnd);
let headerCalls = 0;
const otherReaders = readers();
otherReaders.headersSize = () => { headerCalls++; throw new Error('must not touch headers'); };
const otherResult = O.captureInitForTest(other.root, {}, otherReaders);
assert.strictEqual(otherResult.kind, 'other_origin');
assert.deepStrictEqual(otherResult.origin, {scheme: 'https', host: 'public.example', port: 443});
assert.strictEqual(otherResult.method, 'POST');
assert.strictEqual(headerCalls, 0);
assert(Math.max(...other.shared.reads) <= authorityEnd, 'unknown host path must not be read');
assert(!JSON.stringify(otherResult).includes('/private/path'));
assert(!JSON.stringify(otherResult).includes('OTHER_QUERY_SENTINEL'));

const broken = pointer('https://api.trae.cn/api/route', Infinity, 8);
const brokenResult = O.captureInitForTest(broken.root, {}, readers());
assert.strictEqual(brokenResult.kind, 'invalid_url');

const overHeader = readers();
let headerAtCalls = 0;
overHeader.headersSize = () => 65;
overHeader.headersAt = () => { headerAtCalls++; throw new Error('over limit'); };
const capped = O.captureInitForTest(pointer('https://api.trae.cn/api/ide/v1/chat').root, {}, overHeader);
assert.strictEqual(capped.headers.status, 'over_limit');
assert.strictEqual(headerAtCalls, 0);

console.log(JSON.stringify({javascript_fake_pointer_test: 'passed', cases: 5}));
'''.replace('__JS_PATH__', js_path)
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=20, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(
            json.loads(result.stdout.strip()),
            {"javascript_fake_pointer_test": "passed", "cases": 5},
        )


if __name__ == "__main__":
    unittest.main()
