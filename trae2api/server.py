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


async def _bridge_events(model: str, messages: list[dict], client_tools: list[dict],
                        known_names: set, tool_choice=None) -> AsyncIterator[bytes]:
    """Agent loop: run gateway turns, executing gateway-internal tools locally.

    A call whose name the client declared is emitted as an OpenAI tool_call
    (the client executes it). A call the client does NOT know is executed by
    trae2api itself and its result is fed back as the verified
    "工具执行结果：..." user message, looping until the model finishes.
    """
    from .translate import ToolCallTranslator
    from .tools import ToolExecutor

    executor = ToolExecutor()
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    cur_messages = list(messages)
    max_rounds = int(os.environ.get("TRAE2API_MAX_TOOL_ROUNDS", "8"))

    def emit(chunk: dict) -> bytes:
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()

    def base(delta: dict, finish: str | None = None) -> dict:
        return {"id": chat_id, "object": "chat.completion.chunk", "created": created,
                "model": model, "choices": [{"index": 0, "delta": delta,
                                             "finish_reason": finish}]}

    for _ in range(max_rounds):
        assembler = SSEAssembler()
        translator = ToolCallTranslator()
        calls: list[dict] = []
        usage: dict = {}
        async for raw in gateway.stream_chat(model=model, messages=cur_messages,
                                             tools=client_tools or None,
                                             tool_choice=tool_choice):
            for event, data in assembler.feed(raw.decode("utf-8", "replace")
                                              if isinstance(raw, bytes) else raw):
                if not isinstance(data, dict):
                    continue
                if event == "output":
                    if data.get("reasoning_content"):
                        yield emit(base({"reasoning_content": data["reasoning_content"]}))
                    content = data.get("response") or ""
                    if content:
                        plain, new_calls = translator.feed(content)
                        if plain:
                            yield emit(base({"content": plain}))
                        calls.extend(new_calls)
                elif event == "token_usage":
                    usage = {"prompt_tokens": data.get("prompt_tokens", 0),
                             "completion_tokens": data.get("completion_tokens", 0),
                             "total_tokens": data.get("total_tokens", 0)}
                elif event == "error":
                    yield emit(base({"content": "\n[trae2api error "
                                               f"{data.get('code', '?')}: {data.get('message', '')}]"}))
                    yield emit(base({}, "stop")) + b"data: [DONE]\n\n"
                    return
        residual, more = translator.finish()
        if residual:
            yield emit(base({"content": residual}))
        calls.extend(more)

        client_calls = [c for c in calls if c.get("function", {}).get("name") in known_names]
        internal = [c for c in calls if c.get("function", {}).get("name") not in known_names]

        if client_calls:
            for i, tc in enumerate(client_calls):
                tc["index"] = i
                yield emit(base({"tool_calls": [tc]}))
            yield emit(base({}, "tool_calls")) + b"data: [DONE]\n\n"
            return
        if not internal:
            if usage:
                yield emit({"id": chat_id, "object": "chat.completion.chunk",
                            "created": created, "model": model, "choices": [],
                            "usage": usage})
            yield emit(base({}, "stop")) + b"data: [DONE]\n\n"
            return

        # execute the gateway's tools locally, then continue the loop
        names = ", ".join(tc["function"]["name"] for tc in internal)
        yield emit(base({"content": f"\n[trae2api] 执行工具: {names}\n"}))
        results = []
        for tc in internal:
            name = tc["function"]["name"]
            args = tc["function"].get("arguments") or "{}"
            out = executor.run(name, args)
            results.append(f"[{name}]\n{out if out is not None else '[unsupported tool]'}")
        cur_messages = cur_messages + [
            {"role": "assistant", "content": "",
             "tool_calls": [{**tc, "id": tc.get("id") or f"call_{uuid.uuid4().hex[:24]}"}
                            for tc in internal]},
            {"role": "user", "content": "工具执行结果：\n" + "\n".join(results)},
        ]
    yield emit(base({"content": "\n[trae2api] 达到最大工具轮次，停止。"}))
    yield emit(base({}, "stop")) + b"data: [DONE]\n\n"


def tools_enabled() -> bool:
    return os.environ.get("TRAE2API_EXEC_TOOLS") == "1"


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


async def _translate_events(sse_gen, model: str, include_reasoning: bool = True,
                            tool_filter=None) -> AsyncIterator[bytes]:
    """Convert gateway SSE (progress_notice/prompt/metadata/output/token_usage/done/error)
    into OpenAI chat.completion.chunk SSE, translating Trae's text-embedded
    function-call markup into OpenAI delta.tool_calls.

    tool_filter: optional callable applied to extracted tool calls (used to
    drop gateway-internal tools the client did not declare).
    """
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
    if tool_filter is None:
        tool_filter = lambda calls: calls  # noqa: E731

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
                calls = tool_filter(calls)
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
                calls = tool_filter(calls)
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
        calls = tool_filter(calls)
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
    client_tools = body.get("tools") or []
    known_names = {t.get("function", {}).get("name") for t in client_tools
                   if isinstance(t, dict) and t.get("function", {}).get("name")}
    strict_tools = os.environ.get("TRAE2API_STRICT_TOOLS") == "1"
    drop_foreign = strict_tools and bool(known_names)

    def _filter_calls(calls: list[dict]) -> list[dict]:
        if not drop_foreign:
            return calls
        return [c for c in calls if c.get("function", {}).get("name") in known_names]

    assert gateway is not None
    exec_tools = tools_enabled()
    if stream:
        if exec_tools:
            gen = _bridge_events(model, messages, client_tools, known_names,
                                 tool_choice=body.get("tool_choice"))
        else:
            gen = _translate_events(
                gateway.stream_chat(model=model, messages=messages,
                                    tools=client_tools or None,
                                    tool_choice=body.get("tool_choice")),
                model, tool_filter=_filter_calls)
        return StreamingResponse(
            _safe_sse(gen, model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    # non-stream: buffer the SSE (with local tool execution) then return one response
    from .translate import ToolCallTranslator
    translator = ToolCallTranslator()
    assembler = SSEAssembler()
    exec_tools = tools_enabled()
    cur_messages = list(messages)
    max_rounds = int(os.environ.get("TRAE2API_MAX_TOOL_ROUNDS", "8")) if exec_tools else 1
    try:
        for _ in range(max_rounds):
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: list[dict] = []
            usage: dict = {}
            async for raw in gateway.stream_chat(model=model, messages=cur_messages,
                                                 tools=client_tools or None,
                                                 tool_choice=body.get("tool_choice")):
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
                        raise GatewayError(data.get("code", "unknown"),
                                           data.get("message", "gateway error"))
            residual, more_calls = translator.finish()
            if residual:
                content_parts.append(residual)
            tool_calls.extend(more_calls)
            break_loop = True
            if exec_tools:
                internal = [c for c in tool_calls
                            if c.get("function", {}).get("name") not in known_names]
                client_calls = [c for c in tool_calls
                                if c.get("function", {}).get("name") in known_names]
                if internal and not client_calls:
                    from .tools import ToolExecutor
                    executor = ToolExecutor()
                    results = []
                    for tc in internal:
                        out = executor.run(tc["function"]["name"],
                                           tc["function"].get("arguments") or "{}")
                        results.append(f"[{tc['function']['name']}]\n"
                                       f"{out if out is not None else '[unsupported tool]'}")
                    cur_messages = cur_messages + [
                        {"role": "assistant", "content": "", "tool_calls": internal},
                        {"role": "user", "content": "工具执行结果：\n" + "\n".join(results)},
                    ]
                    # keep looping; discard intermediate prose of tool turns
                    content_parts, reasoning_parts, tool_calls = [], [], []
                    break_loop = False
            if break_loop:
                break
        else:
            content_parts.append("\n[trae2api] 达到最大工具轮次，停止。")
    except GatewayError as e:
        return JSONResponse(status_code=502, content=_error_event(e.code, e.message))
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("trae2api").exception("gateway chat failed")
        return JSONResponse(status_code=502, content=_error_event("internal", str(e)))
    tool_calls = _filter_calls(tool_calls)
    # reindex after filtering
    for i, tc in enumerate(tool_calls):
        tc["index"] = i
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
