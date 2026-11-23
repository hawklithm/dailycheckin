"""Memory-only loopback protocol with synthetic sessions and test-only ledger."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
import uuid

from .fixtures import attributes_for, validate_attributes
from .storage import canonical
from .binding_mock import BINDING_CAPABILITIES, BindingState, SIGNED_PATHS


CAPABILITIES = {"service": "device-registration-lab", "protocol_version": 1, "environment": "sandbox",
                "rewards_enabled": False, "supported_fixture_schema": 1, **BINDING_CAPABILITIES}


class MockState:
    def __init__(self, *, clock=None):
        self.registrations: dict[tuple, dict] = {}
        self.activated: set[tuple] = set()
        self.lock = threading.Lock()
        self.requests = 0
        self.binding = BindingState(self, clock=clock)

    def register(self, body: dict) -> tuple[int, dict]:
        expected = {"experiment_id", "fixture_id", "app_id", "attributes"}
        if set(body) != expected or not valid_context(body):
            return 400, {"accepted": False}
        try:
            validate_attributes(body["attributes"])
            if body["attributes"] != attributes_for(body["fixture_id"]):
                raise ValueError()
        except (ValueError, TypeError):
            return 400, {"accepted": False}
        digest = hashlib.sha256(canonical(body["attributes"]).encode()).hexdigest()
        key = (body["experiment_id"], body["app_id"], digest)
        with self.lock:
            if key not in self.registrations:
                physical = hashlib.sha256(canonical([*key[:2], body["attributes"]["physical_key"]]).encode()).hexdigest()[:32]
                self.registrations[key] = {"accepted": True, "sandbox_device_id": "lab-device-" + uuid.uuid4().hex,
                    "sandbox_install_id": "lab-install-" + uuid.uuid4().hex, "sandbox_physical_id": "lab-physical-" + physical}
            return 200, dict(self.registrations[key])

    def activate(self, body: dict) -> tuple[int, dict]:
        expected = {"experiment_id", "app_id", "sandbox_device_id", "sandbox_install_id"}
        if set(body) != expected or not valid_context(body):
            return 400, {"accepted": False, "activated": False}
        with self.lock:
            found = any(key[:2] == (body["experiment_id"], body["app_id"])
                        and value["sandbox_device_id"] == body["sandbox_device_id"]
                        and value["sandbox_install_id"] == body["sandbox_install_id"]
                        for key, value in self.registrations.items())
            if not found:
                return 400, {"accepted": False, "activated": False}
            self.activated.add((body["experiment_id"], body["sandbox_device_id"], body["sandbox_install_id"]))
        return 200, {"accepted": True, "activated": True}


def valid_context(body: dict) -> bool:
    return (body.get("app_id") == "local-device-lab" and isinstance(body.get("experiment_id"), str)
            and re.fullmatch(r"lab-experiment-[a-z0-9-]{1,64}", body["experiment_id"]) is not None)


class MockServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, host: str = "127.0.0.1", port: int = 0, *, clock=None):
        if host != "127.0.0.1" or type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("mock server must bind to 127.0.0.1 with a valid port")
        self.state = MockState(clock=clock)
        super().__init__((host, port), MockHandler)


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def reply(self, status: int, body: dict) -> None:
        raw = canonical(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        with self.server.state.lock:
            self.server.state.requests += 1
        self.reply(200, CAPABILITIES) if self.path == "/lab/capabilities" else self.reply(404, {"accepted": False})

    def do_POST(self):
        with self.server.state.lock:
            self.server.state.requests += 1
        known = self.path in ("/lab/register", "/lab/activate", "/lab/binding-challenge", "/lab/bind", *SIGNED_PATHS)
        raw, length = None, 0
        try:
            self.connection.settimeout(5)
            length = int(self.headers.get("Content-Length", "0"))
            # A bounded drain also covers rejected requests. Closing a Windows
            # socket with unread body bytes can reset it before 400/404 arrives.
            if 0 < length <= 64 * 1024 and not self.headers.get("Transfer-Encoding"):
                raw = self.rfile.read(length)
        except (ValueError, OSError):
            pass
        if not known:
            self.reply(404, {"accepted": False})
            return
        try:
            if (not 0 < length <= 16 * 1024 or self.headers.get("Transfer-Encoding")
                    or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json"
                    or raw is None or len(raw) != length):
                raise ValueError()
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, OSError, UnicodeError):
            self.reply(400, {"accepted": False})
            return
        methods = {"/lab/register": self.server.state.register, "/lab/activate": self.server.state.activate,
                   "/lab/binding-challenge": self.server.state.binding.challenge, "/lab/bind": self.server.state.binding.bind}
        status, response = (self.server.state.binding.protected(self.path, body) if self.path in SIGNED_PATHS
                            else methods[self.path](body))
        self.reply(status, response)


@contextmanager
def running_mock(*, clock=None):
    server = MockServer(clock=clock)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
