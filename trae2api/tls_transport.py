"""TLS-fingerprint-impersonating gateway transport (default when available).

Trae's network stack is cronet (Chromium). This module provides an httpx-free
transport backed by curl_cffi so the TLS ClientHello (JA3/JA4), HTTP/2 frame
order and header casing match a Chromium-family client instead of OpenSSL.

The server enables this automatically when curl_cffi is importable.
TRAE2API_TLS_IMPERSONATE selects the target (default: chrome124);
set TRAE2API_TLS_IMPERSONATE=off (or =0) to force the plain httpx client.
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator

from .auth import TraeAuth

DEFAULT_IMPERSONATE = os.environ.get("TRAE2API_TLS_IMPERSONATE", "").strip()


class ImpersonatedGateway:
    """Drop-in replacement for TraeGateway's HTTP layer using curl_cffi.

    Mirrors the public surface used by server.py:
      ping(), stream_chat(model, messages, session_id), _headers(), close()
    """

    def __init__(self, auth: TraeAuth, base_url: str = "", impersonate: str = "") -> None:
        from .gateway import DEFAULT_BASE, TraeGateway

        # Reuse TraeGateway for body/header building; replace its client.
        self._inner = TraeGateway(auth, base_url=base_url or DEFAULT_BASE)
        self.impersonate = impersonate or DEFAULT_IMPERSONATE or "chrome124"
        self._session = None

    @property
    def auth(self):  # passthrough for server.py
        return self._inner.auth

    @property
    def base(self):
        return self._inner.base

    def _headers(self) -> dict:
        return self._inner._headers()

    def build_chat_body(self, model: str, messages: list[dict], session_id: str | None = None,
                        tools: list[dict] | None = None, tool_choice=None) -> dict:
        return self._inner.build_chat_body(model, messages, session_id, tools=tools, tool_choice=tool_choice)

    def _get_session(self):
        if self._session is None:
            from curl_cffi.requests import AsyncSession
            self._session = AsyncSession(impersonate=self.impersonate)
        return self._session

    async def web_search(self, query: str, session_id: str = "", top_k: int = 5) -> str:
        return await self._inner.web_search(query, session_id=session_id, top_k=top_k)

    async def ping(self) -> dict:
        s = self._get_session()
        r = await s.post(f"{self.base}/api/ide/v1/ping", json={}, headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def stream_chat(self, model: str, messages: list[dict], session_id: str | None = None,
                          tools: list[dict] | None = None, tool_choice=None) -> AsyncIterator[bytes]:
        body = self.build_chat_body(model, messages, session_id, tools=tools, tool_choice=tool_choice)
        self._inner._trace("request", {"url": f"{self.base}/api/ide/v1/chat", "body": body, "tls": self.impersonate})
        s = self._get_session()
        async with s.stream(
            "POST", f"{self.base}/api/ide/v1/chat", json=body, headers=self._headers()
        ) as r:
            if r.status_code != 200:
                raw = await r.acontent() if hasattr(r, "acontent") else b""
                text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
                self._inner._trace("http_error", {"status": r.status_code, "body": text[:2000]})
                raise GatewayHttpStatus(r.status_code, text[:300])
            async for chunk in r.aiter_content():
                if chunk:
                    self._inner._trace("sse_raw", chunk)
                    yield chunk

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


class GatewayHttpStatus(Exception):
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self.text = text
        super().__init__(f"gateway HTTP {status}: {text}")
