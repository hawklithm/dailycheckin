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
    from .app_storage import root
    root()
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


def _executor_for(messages: list[dict]):
    """Build a ToolExecutor rooted at the workspace the CLIENT reported.

    extra_roots alone is not enough: the executor's PRIMARY workspace decides
    both the default cwd for shell commands and how relative paths resolve. If
    we only passed extra_roots, a command like `Get-ChildItem -Path .` ran in
    the proxy's own install directory instead of the caller's project. So the
    client-reported folder becomes the primary workspace and the proxy's own
    repo is kept as an extra root.
    """
    from .tools import DEFAULT_WORKSPACE, ToolExecutor
    from .context_extract import extract_workspace
    from .debuglog import record

    ws_ctx = extract_workspace(messages)
    if ws_ctx.folders:
        record("workspace_detected", folders=ws_ctx.folders, markers=ws_ctx.raw_markers,
               active_files=ws_ctx.active_files, mentioned=ws_ctx.mentioned)
        primary, extra = ws_ctx.folders[0], list(ws_ctx.folders[1:])
        extra.append(str(DEFAULT_WORKSPACE))
        return ToolExecutor(workspace=primary, extra_roots=extra), ws_ctx
    return ToolExecutor(), ws_ctx


async def _bridge_events(model: str, messages: list[dict], client_tools: list[dict],
                        known_names: set, tool_choice=None) -> AsyncIterator[bytes]:
    """Agent loop: run gateway turns, executing gateway-internal tools locally.

    A call whose name the client declared is emitted as an OpenAI tool_call
    (the client executes it). A call the client does NOT know is executed by
    trae2api itself and its result is fed back as the verified
    "工具执行结果：..." user message, looping until the model finishes.
    """
    from .translate import ToolCallTranslator
    from .debuglog import record

    executor, ws_ctx = _executor_for(messages)
    record("gateway_body", body=gateway_body_for_log(
        model, messages, client_tools, tool_choice))
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
        record("tool_calls_received", names=names,
               calls=[{"name": tc["function"]["name"],
                       "arguments": tc["function"].get("arguments")} for tc in internal])
        results = []
        for tc in internal:
            name = tc["function"]["name"]
            args = tc["function"].get("arguments") or "{}"
            out: str | None = None
            if name in ("web_search", "websearch", "search_web"):
                try:
                    kw = json.loads(args) if args else {}
                    if not isinstance(kw, dict):
                        kw = {"query": str(kw)}
                    query = (kw.get("query") or kw.get("user_input")
                             or kw.get("q") or kw.get("search_term") or "")
                    out = await gateway.web_search(str(query)) if query else "[error] empty query"
                except Exception as e:  # noqa: BLE001
                    out = f"[error] web_search failed: {e}"
            else:
                out = executor.run(name, args)
                if out is None:
                    # Naming the tool matters: a bare "unsupported" hid the fact
                    # that `shell` was missing from the registry for a whole
                    # session while the model kept retrying it.
                    out = (f"[unsupported tool] 代理没有实现工具 {name!r}。"
                           f"请用下列工具之一继续：list_dir / read_file / "
                           f"write_to_file / edit_file_search_replace / "
                           f"search_by_regex / glob / run_shell_command / git。")
            record("tool_executed", name=name, arguments=args, result=(out or "")[:4000])
            results.append(f"[{name}]\n{out}")
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


def gateway_body_for_log(model: str, messages: list[dict], tools, tool_choice) -> dict:
    """Build (and return) the exact gateway body for logging."""
    assert gateway is not None
    return gateway.build_chat_body(model, messages, tools=tools, tool_choice=tool_choice)


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
    from . import events
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

    # unknown/unhandled event names, reported at end of stream (never silent)
    _unseen: dict[str, int] = {}
    # real token usage from the gateway's token_usage event
    _usage: dict = {}

    def _base_chunk(delta: dict, finish: str | None = None,
                    usage: dict | None = None) -> dict:
        chunk = {
            "id": chat_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": delta,
                         "finish_reason": finish}],
        }
        if usage:
            chunk["usage"] = usage
        return chunk

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
                if _unseen:
                    log.info("unhandled gateway events this turn: %s", _unseen)
                if _usage:
                    # emit a final chunk carrying real usage (OpenAI shape)
                    yield _emit(_base_chunk({}, finish, _usage))
                    yield b"data: [DONE]\n\n"
                    return
                yield _final_chunk(chat_id, created, model, finish) + b"data: [DONE]\n\n"
                return
            elif event == "token_usage":
                # Capture real usage instead of discarding it. The OpenAI
                # chunk stream can carry a usage object on the final chunk;
                # we stash it and attach it when the stream ends.
                try:
                    pt = int(data.get("prompt_tokens") or 0)
                    ct = int(data.get("completion_tokens") or 0)
                    tt = int(data.get("total_tokens") or 0) or (pt + ct)
                    if pt or ct or tt:
                        _usage.update({
                            "prompt_tokens": pt,
                            "completion_tokens": ct,
                            "total_tokens": tt,
                        })
                except (TypeError, ValueError):
                    pass
                continue
            elif event in ("metadata", "prompt", "progress_notice"):
                if event == "metadata":
                    if log.isEnabledFor(10):
                        log.debug("metadata: %s", json.dumps(data)[:200])
                continue
            elif not events.is_known(event):
                # An unknown event used to vanish silently. If the gateway
                # starts emitting richer agent-mode events (thought, tool_call,
                # context_usage ...) we want to notice, not guess.
                _unseen[event] = _unseen.get(event, 0) + 1
                if log.isEnabledFor(10):
                    log.debug("unhandled event %r: %s", event,
                              json.dumps(data)[:200])
                continue
    if not saw_done:
        if _unseen:
            log.info("unhandled gateway events this turn: %s", _unseen)
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
        if _usage:
            yield _emit(_base_chunk({}, finish, _usage))
            yield b"data: [DONE]\n\n"
            return
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
    from .debuglog import record, text_of
    record("client_request", model=model, stream=stream,
           tools=[t.get("function", {}).get("name") for t in (body.get("tools") or [])
                  if isinstance(t, dict)],
           messages=[{"role": m.get("role"), "content": text_of(m.get("content"))[:2000]}
                     for m in messages if isinstance(m, dict)])
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
    from .debuglog import record
    record("gateway_body", body=gateway_body_for_log(
        model, messages, client_tools, body.get("tool_choice")),
        exec_tools=exec_tools,
        builder=os.environ.get("TRAE2API_FORCE_CHAT") != "1")
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
                    from .debuglog import record
                    executor, _ = _executor_for(cur_messages)
                    record("tool_calls_received", stream=False,
                           calls=[{"name": tc["function"]["name"],
                                   "arguments": tc["function"].get("arguments")}
                                  for tc in internal])
                    results = []
                    for tc in internal:
                        name = tc["function"]["name"]
                        args = tc["function"].get("arguments") or "{}"
                        out: str | None = None
                        if name in ("web_search", "websearch", "search_web"):
                            try:
                                kw = json.loads(args) if args else {}
                                if not isinstance(kw, dict):
                                    kw = {"query": str(kw)}
                                query = (kw.get("query") or kw.get("user_input")
                                         or kw.get("q") or kw.get("search_term") or "")
                                out = (await gateway.web_search(str(query))
                                       if query else "[error] empty query")
                            except Exception as e:  # noqa: BLE001
                                out = f"[error] web_search failed: {e}"
                        else:
                            out = executor.run(name, args)
                            if out is None:
                                out = (f"[unsupported tool] 代理没有实现工具 {name!r}；"
                                       f"可用工具见代理启动日志。请换用其它工具继续。")
                        record("tool_executed", name=name, arguments=args,
                               result=(out or "")[:4000])
                        results.append(f"[{name}]\n{out}")
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
    from .debuglog import record
    record("client_response", stream=False, finish_reason=finish_reason,
           content="".join(content_parts)[:4000],
           reasoning=("".join(reasoning_parts)[:2000] if reasoning_parts else ""),
           tool_calls=[{"name": tc["function"]["name"],
                        "arguments": tc["function"].get("arguments")} for tc in tool_calls],
           usage=usage)
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
