"""OpenAI-compatible FastAPI server exposing Trae AI gateway capabilities.

Endpoints:
  GET  /v1/models                       - model catalog (from cached catalog + gateway)
  POST /v1/chat/completions             - chat (streams via SSE, passthrough or translated)
  GET  /health                          - liveness + auth status

Run: python -m trae2api   (env: TRAE2API_PORT, TRAE2API_API_KEY, TRAE2API_GATEWAY)
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import TraeAuth
from .gateway import TraeGateway, GatewayError
from .model_catalog import ModelCatalog

PORT = int(os.environ.get("TRAE2API_PORT", "8080"))
LOCAL_API_KEY = os.environ.get("TRAE2API_API_KEY", "")  # optional client auth

app = FastAPI(title="trae2api", version="0.1.0")
auth = TraeAuth()
gateway: Optional[TraeGateway] = None
catalog: Optional[ModelCatalog] = None


@app.on_event("startup")
async def _startup() -> None:
    global gateway, catalog
    creds = auth.load()
    base = os.environ.get("TRAE2API_GATEWAY", "") or None
    impersonate = os.environ.get("TRAE2API_TLS_IMPERSONATE", "chrome124").strip()
    if impersonate.lower() in ("off", "0", "false", "none", ""):
        gateway = TraeGateway(auth, base_url=base)
        print("[trae2api] TLS impersonation disabled (plain httpx)")
    else:
        try:
            from .tls_transport import ImpersonatedGateway
            gateway = ImpersonatedGateway(auth, base_url=base or "", impersonate=impersonate)
            print(f"[trae2api] TLS impersonation enabled: {impersonate}")
        except ImportError:
            print("[trae2api] curl_cffi not installed; falling back to httpx "
                  "(pip install curl_cffi to enable TLS fingerprint impersonation)")
            gateway = TraeGateway(auth, base_url=base)
    catalog = ModelCatalog.load_default()
    print(f"[trae2api] loaded credentials for user {creds.user_id} (region {creds.region})")


def _check_client_auth(request: Request) -> None:
    if not LOCAL_API_KEY:
        return
    header = request.headers.get("authorization", "")
    if header != f"Bearer {LOCAL_API_KEY}":
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/health")
async def health() -> dict:
    ok = auth.token_valid()
    return {
        "status": "ok" if ok else "token_invalid",
        "user_id": auth.creds.user_id,
        "region": auth.creds.region,
        "jwt_valid": ok,
        "jwt_exp": auth.creds.jwt_exp,
    }


@app.get("/v1/models")
async def list_models(request: Request):
    _check_client_auth(request)
    assert catalog is not None
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "owned_by": "trae"}
            for m in catalog.model_names()
        ],
    }


def _error_event(code: str, message: str) -> dict:
    return {"error": {"message": message, "type": "trae_error", "code": code}}


class SSEAssembler:
    """Stateful SSE line reassembler.

    Raw gateway chunks split SSE lines arbitrarily (observed live: the `data:`
    prefix and its JSON payload can land in different TCP chunks). Lines are
    buffered until complete, so events are never lost or truncated.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._event: str | None = None

    def feed(self, text: str) -> list[tuple[str, dict]]:
        self._buf += text
        events: list[tuple[str, dict]] = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip("\r").strip()
            if not line:
                continue  # event separator
            if line.startswith("event:"):
                self._event = line[6:].strip()
            elif line.startswith("data:"):
                data_text = line[5:].strip()
                payload: dict = {}
                if data_text:
                    try:
                        payload = json.loads(data_text)
                    except json.JSONDecodeError:
                        payload = {"raw": data_text}
                events.append((self._event or "", payload or {}))
                self._event = None
        return events


def _parse_sse_lines(text: str):
    """Backward-compatible single-shot parser (complete text only)."""
    yield from SSEAssembler().feed(text)


async def _safe_sse(gen, model: str) -> AsyncIterator[bytes]:
    """Wrap gateway SSE so exceptions become SSE error events, not HTTP 500s."""
    try:
        async for chunk in gen:
            yield chunk
    except GatewayError as e:
        err = {"error": {"message": e.message, "type": "trae_error", "code": e.code}}
        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode()
        yield b"data: [DONE]\n\n"
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("trae2api").exception("gateway stream failed")
        err = {"error": {"message": f"proxy failure: {e}", "type": "trae_error", "code": "internal"}}
        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode()
        yield b"data: [DONE]\n\n"


async def _translate_events(sse_gen, model: str, include_reasoning: bool = True) -> AsyncIterator[bytes]:
    """Convert gateway SSE (progress_notice/prompt/metadata/output/token_usage/done/error)
    into OpenAI chat.completion.chunk SSE, translating Trae's text-embedded
    function-call markup into OpenAI delta.tool_calls."""
    import logging
    from .translate import ToolCallTranslator
    log = logging.getLogger("trae2api")
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    saw_done = False
    saw_tool_calls = False
    tc_index = 0
    assembler = SSEAssembler()
    translator = ToolCallTranslator()

    def _base_chunk(delta: dict, finish: str | None = None) -> dict:
        return {
            "id": chat_id, "object": "chat.completion.chunk", "created": created,
            "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    def _emit(chunk: dict) -> bytes:
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()

    async for raw in sse_gen:
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        for event, data in assembler.feed(text):
            if not isinstance(data, dict):
                continue
            if event == "output":
                reasoning = data.get("reasoning_content") or ""
                if reasoning and include_reasoning:
                    yield _emit(_base_chunk({"reasoning_content": reasoning}))
                content = data.get("response") or ""
                if not content:
                    continue
                plain, calls = translator.feed(content)
                if plain:
                    yield _emit(_base_chunk({"content": plain}))
                for tc in calls:
                    tc["index"] = tc_index
                    tc_index += 1
                    saw_tool_calls = True
                    yield _emit(_base_chunk({"tool_calls": [tc]}))
            elif event == "error":
                msg = data.get("message") or "gateway error"
                code = data.get("code") or "unknown"
                delta = {"content": f"\n[trae2api error {code}: {msg}]"}
                chunk = {
                    "id": chat_id, "object": "chat.completion.chunk", "created": created,
                    "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
                yield _final_chunk(chat_id, created, model) + b"data: [DONE]\n\n"
                return
            elif event == "done":
                saw_done = True
                # flush the translator: residual text and finish_reason
                residual, calls = translator.finish()
                if residual:
                    yield _emit(_base_chunk({"content": residual}))
                for tc in calls:
                    tc["index"] = tc_index
                    tc_index += 1
                    saw_tool_calls = True
                    yield _emit(_base_chunk({"tool_calls": [tc]}))
                finish = "tool_calls" if saw_tool_calls else "stop"
                yield _final_chunk(chat_id, created, model, finish) + b"data: [DONE]\n\n"
                return
            elif event in ("metadata", "prompt", "progress_notice", "token_usage"):
                if event == "metadata" and log.isEnabledFor(10):
                    log.debug("metadata: %s", json.dumps(data)[:200])
                continue
    if not saw_done:
        residual, calls = translator.finish()
        if residual:
            yield _emit(_base_chunk({"content": residual}))
        for tc in calls:
            tc["index"] = tc_index
            tc_index += 1
            saw_tool_calls = True
            yield _emit(_base_chunk({"tool_calls": [tc]}))
        finish = "tool_calls" if saw_tool_calls else "stop"
        yield _final_chunk(chat_id, created, model, finish) + b"data: [DONE]\n\n"


def _final_chunk(chat_id: str, created: int, model: str, finish: str = "stop") -> bytes:
    chunk = {
        "id": chat_id, "object": "chat.completion.chunk", "created": created,
        "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
    }
    return f"data: {json.dumps(chunk)}\n\n".encode()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    _check_client_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    model = body.get("model") or "trae-default"
    stream = bool(body.get("stream", False))
    messages = body.get("messages") or []
    if not messages:
        raise HTTPException(status_code=400, detail="messages required")

    assert gateway is not None
    if stream:
        gen = gateway.stream_chat(model=model, messages=messages)
        return StreamingResponse(
            _safe_sse(_translate_events(gen, model), model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    # non-stream: buffer the SSE then return a complete OpenAI response
    from .translate import ToolCallTranslator
    translator = ToolCallTranslator()
    assembler = SSEAssembler()
    try:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[dict] = []
        usage: dict = {}
        async for raw in gateway.stream_chat(model=model, messages=messages):
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            for event, data in assembler.feed(text):
                if not isinstance(data, dict):
                    continue
                if event == "output":
                    if data.get("reasoning_content"):
                        reasoning_parts.append(data["reasoning_content"])
                    content = data.get("response") or ""
                    if content:
                        plain, calls = translator.feed(content)
                        if plain:
                            content_parts.append(plain)
                        tool_calls.extend(calls)
                elif event == "token_usage":
                    usage = {
                        "prompt_tokens": data.get("prompt_tokens", 0),
                        "completion_tokens": data.get("completion_tokens", 0),
                        "total_tokens": data.get("total_tokens", 0),
                    }
                elif event == "error":
                    raise GatewayError(data.get("code", "unknown"), data.get("message", "gateway error"))
        residual, more_calls = translator.finish()
        if residual:
            content_parts.append(residual)
        tool_calls.extend(more_calls)
    except GatewayError as e:
        return JSONResponse(status_code=502, content=_error_event(e.code, e.message))
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("trae2api").exception("gateway chat failed")
        return JSONResponse(status_code=502, content=_error_event("internal", str(e)))
    message: dict = {"role": "assistant", "content": "".join(content_parts)}
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
    if tool_calls:
        message["tool_calls"] = tool_calls
    finish_reason = "tool_calls" if tool_calls else "stop"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
