"""Trae AI gateway client (V1 HTTP path, SSE streaming).

Established by reverse engineering + live probing:
  base: https://trae-api-cn.mchost.guru
  auth: Authorization: Cloud-IDE-JWT <jwt>   (+ X-User-Region: CN)
  POST /api/ide/v1/ping         -> {"message":"pong"}
  POST /api/ide/v1/chat         -> SSE stream (event: Meta/Output/Done/Error)
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx

from .auth import TraeAuth

DEFAULT_BASE = "https://trae-api-cn.mchost.guru"


class GatewayError(Exception):
    def __init__(self, code, message: str) -> None:
        self.code = str(code)
        self.message = message or "gateway error"
        super().__init__(f"[{self.code}] {self.message}")


class TraeGateway:
    TRACE_DIR = Path(os.environ.get("TRAE2API_TRACE_DIR", Path(__file__).parent / "trace"))

    def __init__(self, auth: TraeAuth, base_url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.auth = auth
        self.base = (base_url or os.environ.get("TRAE2API_GATEWAY") or DEFAULT_BASE).rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))
        self._trace_file = None
        self._trace_seq = 0

    def _trace(self, kind: str, data) -> None:
        """Append raw wire events to trace/<ts>-<seq>.jsonl (TRAE2API_TRACE=off to disable)."""
        if os.environ.get("TRAE2API_TRACE", "1").lower() in ("off", "0", "false"):
            return
        try:
            if self._trace_file is None:
                self.TRACE_DIR.mkdir(parents=True, exist_ok=True)
                path = self.TRACE_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.jsonl"
                self._trace_file = open(path, "a", encoding="utf-8")
                self._trace_seq = 0
            self._trace_seq += 1
            rec = {"ts": time.time(), "seq": self._trace_seq, "kind": kind}
            if isinstance(data, bytes):
                data = data.decode("utf-8", "replace")
            rec["data"] = data
            self._trace_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._trace_file.flush()
        except Exception:
            pass

    # Device fingerprint values observed from a real Trae client on this
    # machine (completion.log). Override via env to match a different host.
    DEV_CPU = os.environ.get("TRAE2API_DEV_CPU", "AMD")
    DEV_MODEL = os.environ.get("TRAE2API_DEV_MODEL", "MS-7B89")
    DEV_OS_TYPE = os.environ.get("TRAE2API_DEV_OS_TYPE", "windows")
    DEV_OS_VERSION = os.environ.get("TRAE2API_DEV_OS_VERSION", "Windows 10 Education")
    USER_AGENT = os.environ.get("TRAE2API_UA", "trae-cn/3.4.4")

    def _headers(self) -> dict:
        jwt = self.auth.get_jwt()
        d = self.auth.device
        from urllib.parse import quote
        h = {
            "Authorization": f"Cloud-IDE-JWT {jwt}",
            "x-ide-token": jwt,
            "X-User-Region": self.auth.creds.region,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": self.USER_AGENT,
            "X-App-Id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
            "x-plugin-channel": "icube-ai",
            "x-ide-version-code": "20260212",
            "X-Trae-Client-Type": "ide",
            "X-Device-Cpu": quote(d.device_cpu or self.DEV_CPU),
            "X-Device-Brand": quote(d.device_brand or self.DEV_MODEL),
            "X-Device-Type": quote(d.os_info.lower() if d.os_info else self.DEV_OS_TYPE),
            "X-Os-Version": quote(d.os_version or self.DEV_OS_VERSION),
        }
        if d.device_id:
            h["X-Device-Id"] = d.device_id
        if d.machine_id:
            h["X-Machine-Id"] = d.machine_id
        return h

    async def ping(self) -> dict:
        r = await self.client.post(f"{self.base}/api/ide/v1/ping", json={}, headers=self._headers())
        r.raise_for_status()
        return r.json()

    @staticmethod
    def build_chat_body(model: str, messages: list[dict], session_id: str | None = None) -> dict:
        """Translate OpenAI-style messages into the gateway /chat body.

        Uses translate.normalize_messages so that:
        - system messages are preserved (prefixed to the first user turn)
        - assistant.tool_calls are re-rendered as Trae function-call markup
        - role:"tool"/"function" results become a user turn
          "工具执行结果：\\n..." (the shape the gateway accepts, verified live)
        """
        from .translate import normalize_messages, trae_history_and_input

        session_id = session_id or str(uuid.uuid4())
        turns = normalize_messages(messages)
        user_text, chat_history = trae_history_and_input(turns)
        chat_history = chat_history[-24:]
        body = {
            "user_input": user_text,
            "session_id": session_id,
            "chat_history": chat_history,
        }
        # The gateway rejects unknown model_name values (4023). The IDE's own
        # model routing happens native-side; the server default is used when
        # model_name is omitted. TRAE2API_MODEL overrides everything; the
        # caller's model name is honored only when it is non-empty AND the
        # operator sets TRAE2API_PASSTHROUGH_MODEL=1 (experimental).
        forced = os.environ.get("TRAE2API_MODEL", "").strip()
        passthrough = os.environ.get("TRAE2API_PASSTHROUGH_MODEL") == "1"
        if forced:
            body["model_name"] = forced
        elif passthrough and model and model.strip():
            body["model_name"] = model.strip()
        return body

    async def stream_chat(self, model: str, messages: list[dict], session_id: str | None = None) -> AsyncIterator[bytes]:
        """Yield raw SSE byte chunks from POST /api/ide/v1/chat."""
        body = self.build_chat_body(model, messages, session_id)
        self._trace("request", {"url": f"{self.base}/api/ide/v1/chat", "body": body})
        async with self.client.stream(
            "POST", f"{self.base}/api/ide/v1/chat", json=body, headers=self._headers()
        ) as r:
            if r.status_code != 200:
                text = (await r.aread()).decode("utf-8", "replace")
                self._trace("http_error", {"status": r.status_code, "body": text[:2000]})
                raise GatewayError(r.status_code, f"gateway HTTP {r.status_code}: {text[:200]}")
            async for chunk in r.aiter_bytes():
                self._trace("sse_raw", chunk)
                yield chunk

    async def close(self) -> None:
        await self.client.aclose()
