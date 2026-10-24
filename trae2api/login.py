"""Full OAuth login flow for Trae CN — no local Trae installation required.

Reverse engineered from out-build/vs/code/electron-main/oauth/marscode/ (login.js,
userLogin/loginUrlBuilder.js, oauthLocalServer.js):

1. Generate a device identity (device_id, machine_id, ECDSA P-256 keypair) and
   a PKCE pair (S256).
2. Serve a one-shot local HTTP server on 127.0.0.1:<random> listening for
   GET /authorize (also /login-confirm, /login-success).
3. Open the browser at
   {consoleHost}/authorization?login_version=1&auth_from=trae&login_channel=native_ide
   &auth_type=local&client_id={ClientID}&redirect=0&login_trace_id={uuid}
   &auth_callback_url=http://127.0.0.1:{port}/authorize&machine_id=...&device_id=...
   &x_device_id=...&x_machine_id=...&x_device_brand=...&x_device_type=...
   &x_os_version=...&x_app_version=...&x_app_type=trae
   &code_challenge={S256}&code_challenge_method=S256
4. The web app redirects back with authCodeInfo={"AuthCode": "..."} (URL-encoded JSON).
5. POST {apiHost}/trae/api/v3/oauth/ExchangeToken
   {ClientID, AuthCode, CodeVerifier, DeviceInfo, IDEVersion}   (no DeviceProof)
   -> Result.{Token, RefreshToken, TokenExpireAt, TokenExpireDuration, RefreshExpireAt}
6. POST {apiHost}/cloudide/api/v3/trae/GetUserInfo (x-cloudide-token) for the profile.
7. Persist everything to trae2api.json (same format TraeAuth.load() consumes).

Usage:  python -m trae2api login [--timeout 1800] [--no-browser]
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .auth import DEFAULT_CLIENT_ID, IDE_VERSION, TraeAuth

CONSOLE_HOST = os.environ.get("TRAE2API_CONSOLE_HOST", "https://www.trae.cn")
API_HOST = os.environ.get("TRAE2API_API_HOST", "https://api.trae.cn")
SUCCESS_HTML = "<html><body><h3>trae2api: login received. You can close this tab.</h3></body></html>"


def _rand_device_id(n: int = 14) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _rand_machine_id() -> str:
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


class TraeLoginFlow:
    def __init__(
        self,
        client_id: str = DEFAULT_CLIENT_ID,
        console_host: str = CONSOLE_HOST,
        api_host: str = API_HOST,
        creds_file: str | os.PathLike | None = None,
        device_name: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.console_host = console_host.rstrip("/")
        self.api_host = api_host.rstrip("/")
        self.creds_file = Path(creds_file) if creds_file else Path(__file__).parent / "trae2api.json"

        # device identity
        self.device_id = _rand_device_id()
        self.machine_id = _rand_machine_id()
        self.device_name = device_name or f"{os.environ.get('USERNAME') or os.environ.get('USER') or 'trae'}2api"
        self.os_name = "Windows" if os.name == "nt" else ("Darwin" if sys_platform() == "darwin" else "Linux")
        self.os_version = os_version_string()
        self.device_cpu = os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64")

        key = ec.generate_private_key(ec.SECP256R1())
        self.private_key_pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        self.public_key_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

        # PKCE (Mxe(): verifier 48 random bytes base64url, challenge sha256 b64url)
        self.code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
        self.code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self.code_verifier.encode()).digest()
        ).decode().rstrip("=")

        self.login_trace_id = str(uuid.uuid4())
        self.result: dict = {}
        self.error_code: str | None = None
        self._server: ThreadingHTTPServer | None = None
        self._done = threading.Event()

    # ---------- local callback server ----------

    def _start_server(self) -> int:
        flow = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                if parsed.path == "/authorize":
                    err = qs.get("error_code")
                    if err:
                        flow.error_code = err
                    auth_info_raw = qs.get("authCodeInfo", "")
                    try:
                        auth_info = json.loads(auth_info_raw) if auth_info_raw else {}
                    except json.JSONDecodeError:
                        auth_info = {}
                    auth_code = auth_info.get("AuthCode", "")
                    if auth_code:
                        flow.result["AuthCode"] = auth_code
                        flow.result["userInfo"] = qs.get("userInfo", "")
                    else:
                        flow.error_code = flow.error_code or "no_auth_code"
                    self._respond(SUCCESS_HTML)
                    flow._done.set()
                elif parsed.path in ("/login-confirm", "/login-success"):
                    self._respond(SUCCESS_HTML)
                    flow._done.set()
                else:
                    self._respond("<html><body>unknown path</body></html>", 404)

            def _respond(self, body: str, code: int = 200) -> None:
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, fmt, *args):  # silence default logging
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = self._server.server_address[1]
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()
        return port

    # ---------- login url ----------

    def build_login_url(self, port: int) -> str:
        callback = f"http://127.0.0.1:{port}/authorize"
        params = {
            "login_version": "1",
            "auth_from": "trae",
            "login_channel": "native_ide",
            "plugin_version": "local",
            "auth_type": "local",
            "client_id": self.client_id,
            "redirect": "0",
            "login_trace_id": self.login_trace_id,
            "auth_callback_url": callback,
            "machine_id": self.machine_id,
            "device_id": self.device_id,
            "x_device_id": self.device_id,
            "x_machine_id": self.machine_id,
            "x_device_brand": self.device_name,
            "x_device_type": self.os_name,
            "x_os_version": self.os_version,
            "x_app_version": IDE_VERSION,
            "x_app_type": "trae",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.console_host}/authorization?{urlencode(params)}"

    # ---------- exchange ----------

    def _device_info(self) -> dict:
        return {
            "DeviceID": self.device_id,
            "MachineID": self.machine_id,
            "PlatformCode": "IDE_PC",
            "DeviceType": "PC",
            "DeviceName": self.device_name,
            "DeviceModel": self.device_name,
            "ClientVersion": IDE_VERSION,
            "DevicePublicKey": self.public_key_pem,
            "DeviceBrand": self.device_name,
            "DeviceCPU": self.device_cpu,
            "OSInfo": self.os_name,
            "OSVersion": self.os_version,
        }

    def _post_json(self, url: str, body: dict, token: str = "") -> dict:
        req = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "x-cloudide-token": token},
        )
        with urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))

    def exchange_auth_code(self, auth_code: str) -> dict:
        url = f"{self.api_host}/trae/api/v3/oauth/ExchangeToken"
        body = {
            "ClientID": self.client_id,
            "AuthCode": auth_code,
            "CodeVerifier": self.code_verifier,
            "DeviceInfo": self._device_info(),
            "IDEVersion": IDE_VERSION,
        }
        data = self._post_json(url, body)
        err = (data.get("ResponseMetadata") or {}).get("Error") or {}
        if err.get("Code"):
            raise RuntimeError(f"ExchangeToken error {err.get('Code')}: {err.get('Message')}")
        result = data.get("Result") or {}
        if not result.get("Token"):
            raise RuntimeError(f"ExchangeToken returned no Token: {json.dumps(data)[:300]}")
        return result

    def fetch_user_info(self, token: str) -> dict:
        url = f"{self.api_host}/cloudide/api/v3/trae/GetUserInfo"
        body = {"ReqSource": "IDE", "IDEVersion": IDE_VERSION}
        try:
            data = self._post_json(url, body, token=token)
            return (data.get("Result") or {})
        except Exception:
            return {}

    # ---------- orchestration ----------

    def start(self, open_browser: bool = True, timeout_sec: float = 1800.0, log=print) -> TraeAuth:
        port = self._start_server()
        url = self.build_login_url(port)
        log("=" * 70)
        log("trae2api login: open this URL in your browser and complete sign-in:")
        log(url)
        log("=" * 70)
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        if not self._done.wait(timeout_sec):
            raise TimeoutError("login timed out waiting for the OAuth callback")
        if self.error_code and "AuthCode" not in self.result:
            raise RuntimeError(f"login failed: error_code={self.error_code}")
        auth_code = self.result["AuthCode"]
        log("[login] received auth code, exchanging tokens ...")
        result = self.exchange_auth_code(auth_code)
        log("[login] exchange ok, fetching user info ...")
        profile = self.fetch_user_info(result["Token"])

        auth = TraeAuth(creds_file=self.creds_file)
        auth.creds.token = result["Token"]
        auth.creds.refresh_token = result.get("RefreshToken", "")
        auth.creds.expired_at = _iso_from_ms_or_iso(result.get("TokenExpireAt"), result.get("TokenExpireDuration"))
        auth.creds.refresh_expired_at = _iso_from_ms_or_iso(result.get("RefreshExpireAt"))
        auth.creds.token_release_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        auth.creds.user_id = str(profile.get("UserID") or result.get("UserID") or "")
        auth.creds.host = self.api_host
        auth.creds.region = profile.get("AIRegion") or profile.get("Region") or "CN"
        auth.creds.username = profile.get("ScreenName", "")
        auth.creds.jwt = result["Token"]
        from .auth import _jwt_exp
        auth.creds.jwt_exp = _jwt_exp(result["Token"])
        auth.creds.extra = {"tenant_id": profile.get("TenantID", "")}

        auth.device.device_id = self.device_id
        auth.device.machine_id = self.machine_id
        auth.device.device_name = self.device_name
        auth.device.device_model = self.device_name
        auth.device.device_brand = self.device_name
        auth.device.device_cpu = self.device_cpu
        auth.device.os_info = self.os_name
        auth.device.os_version = self.os_version
        auth.private_key = serialization.load_pem_private_key(self.private_key_pem.encode(), password=None)

        auth.save()
        log(f"[login] credentials saved to {self.creds_file}")
        log(f"[login] user {auth.creds.user_id} ({auth.creds.username or 'unknown'}) region={auth.creds.region}")
        log(f"[login] token expires {auth.creds.expired_at}, refresh expires {auth.creds.refresh_expired_at}")
        self._server.shutdown()
        return auth


def _iso_from_ms_or_iso(value, duration_ms=None) -> str:
    from datetime import datetime, timezone
    try:
        if value is None and duration_ms:
            return (datetime.now(timezone.utc).fromtimestamp(time.time() + float(duration_ms) / 1000)).isoformat().replace("+00:00", "Z")
        if value is None:
            return ""
        v = float(value)
        if v > 10_000_000_000:  # ms epoch
            return datetime.fromtimestamp(v / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if v > 10_000_000:  # s epoch
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        pass
    return str(value or "")


def os_version_string() -> str:
    try:
        import platform
        if os.name == "nt":
            v = platform.win32_ver()[0] or "10"
            return f"Windows {v} " + (platform.win32_ver()[3] or "").split("-")[0] if False else f"Windows {v}"
        return platform.platform()
    except Exception:
        return "Windows 10"


def sys_platform() -> str:
    import sys
    return sys.platform


def run_login(timeout_sec: float = 1800.0, open_browser: bool = True) -> TraeAuth:
    flow = TraeLoginFlow()
    return flow.start(open_browser=open_browser, timeout_sec=timeout_sec)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(prog="trae2api login")
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run_login(timeout_sec=args.timeout, open_browser=not args.no_browser)
