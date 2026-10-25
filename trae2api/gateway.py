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
    def render_tool_declarations(tools: list[dict], tool_choice=None) -> str:
        """Render OpenAI tool definitions as an in-prompt tool section.

        The gateway injects its own IDE toolset (ide_prompts); without this
        section the model calls Trae-internal tools (list_dir, ...) that the
        client cannot execute. Declaring the client's tools in the prompt
        steers the model to emit calls the client actually knows.
        tool_choice mirrors OpenAI semantics: "auto"/"none"/"required" or
        {"type":"function","function":{"name":...}}.
        """
        if not tools:
            return ""
        lines = [
            "【可用工具】",
            "你可以使用以下工具。调用时必须严格使用如下格式（一行内完成）：",
            '<|FunctionCallBegin|>[{"name":"工具名","parameters":{参数对象}}]<|FunctionCallEnd|>',
            "工具执行结果会以用户消息「工具执行结果：…」回传，收到后再继续回答。",
            "",
        ]
        for t in tools:
            if t.get("type") != "function":
                continue
            fn = t.get("function") or {}
            name = fn.get("name") or ""
            if not name:
                continue
            desc = (fn.get("description") or "").strip()
            params = fn.get("parameters")
            lines.append(f"- name: {name}")
            if desc:
                lines.append(f"  说明: {desc}")
            if params:
                try:
                    lines.append(f"  参数schema: {json.dumps(params, ensure_ascii=False)}")
                except (TypeError, ValueError):
                    pass
        lines.append("")
        lines.append("除上述工具外，不要调用任何其他工具。")
        if tool_choice is not None:
            if tool_choice == "none":
                lines.append("本轮禁止调用任何工具，直接用文字回答。")
            elif tool_choice == "required":
                lines.append("本轮必须调用上述某一个工具。")
            elif isinstance(tool_choice, dict):
                name = ((tool_choice.get("function") or {}).get("name")
                        or tool_choice.get("name") or "")
                if name:
                    lines.append(f"本轮必须调用工具 {name}。")
        return "\n".join(lines)

    @staticmethod
    def build_chat_body(model: str, messages: list[dict], session_id: str | None = None,
                        tools: list[dict] | None = None, tool_choice=None) -> dict:
        """Translate OpenAI-style messages into the gateway /chat body.

        Uses translate.normalize_messages so that:
        - system messages are preserved (prefixed to the first user turn)
        - assistant.tool_calls are re-rendered as Trae function-call markup
        - role:"tool"/"function" results become a user turn
          "工具执行结果：\\n..." (the shape the gateway accepts, verified live)
        """
        from .translate import normalize_messages, trae_history_and_input
        from .context_extract import extract_workspace

        session_id = session_id or str(uuid.uuid4())
        # The client's system prompt is NOT part of the user-visible turn: the
        # real IDE sends only the user's own text in message_content/user_input
        # (its system prompt is assembled server-side as ide_prompts). We keep
        # the harness's system text out of the turn but still mine it for the
        # working directory, so extract_workspace() runs on the raw messages.
        ws = extract_workspace(messages)
        turns = normalize_messages(messages)
        if tools:
            rendered = TraeGateway.render_tool_declarations(tools, tool_choice)
            if rendered:
                turns = [("system", rendered)] + turns
        user_text, chat_history = trae_history_and_input(turns, drop_system=True)
        chat_history = chat_history[-24:]
        body = {
            "user_input": user_text,
            "session_id": session_id,
            "chat_history": chat_history,
        }
        # --- IDE-shaped context (what the real Trae client sends) -------------
        # Trae's own client derives these from the VSCode APIs; an OpenAI
        # caller carries the same information inside its messages (Claude Code
        # "Working directory:", Codex <environment>, Cline system-reminder,
        # inline @paths), so we mine it there. See context_extract.py.
        ws = extract_workspace(messages)
        if ws.folders:
            body["workspace_folders"] = ws.folders_payload()
            body["mention_context"] = ws.mention_context()
            body["parsed_query"] = [
                {"type": "folder", "path": p} for p in ws.folders
            ] + [{"type": "file", "file_path": p} for p in ws.active_files + ws.mentioned]
        if ws.active_files or ws.mentioned:
            body["code_selections"] = []
        # agent_type / scene_location / agent.
        # Decoded rule (createChatRequestObject -> getChatRequestAgentType):
        #   let agentType = agent ? agent.type : 'chat';
        #   return sceneLocation === 1 ? 'chat' : agentType;
        # SceneLocation enum has exactly two values: 1 = inline chat (forces
        # 'chat'), 2 = the AI sidebar "Chatview". Builder therefore needs
        # scene_location = 2 plus an agent whose type is 'builder'.
        #
        # Default is BUILDER for every request: it carries the full IDE toolset
        # and prompt, which is what an agent client wants. Set
        # TRAE2API_FORCE_CHAT=1 to fall back to the lightweight chat template.
        force_chat = os.environ.get("TRAE2API_FORCE_CHAT") == "1"
        if force_chat:
            builder_mode = False
        else:
            builder_mode = True
        if builder_mode:
            body["agent_type"] = os.environ.get("TRAE2API_AGENT_TYPE") or "builder"
            body["scene_location"] = 2
            body["agent"] = {"type": "builder", "name": "builder", "title": "Builder"}
        else:
            body["agent_type"] = "chat"
            body["scene_location"] = 1
        # structured message body (what the IDE sends instead of free text)
        body["message_content"] = [{"type": "text", "text_content": user_text}]
        body["message_id"] = str(uuid.uuid4())
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

    async def web_search(self, query: str, session_id: str = "", top_k: int = 5) -> str:
        """POST /api/ide/v1/web_search — same call the IDE's own client makes."""
        body = {
            "user_input": query,
            "top_k": top_k,
            "session_id": session_id or str(uuid.uuid4()),
            "language": "zh-CN",
        }
        r = await self.client.post(f"{self.base}/api/ide/v1/web_search", json=body,
                                   headers=self._headers(), timeout=60.0)
        if r.status_code != 200:
            return f"[error] web_search HTTP {r.status_code}: {r.text[:200]}"
        try:
            data = r.json()
        except Exception:
            return f"[error] web_search bad json: {r.text[:200]}"
        result = data.get("Result") or data.get("result") or data
        if isinstance(result, dict):
            # observed shape: {"references": [{"title","uri","snippets":[...],"source"}]}
            refs = result.get("references") or result.get("documents") or []
            if isinstance(refs, list) and refs:
                lines = []
                for it in refs[:top_k]:
                    if not isinstance(it, dict):
                        continue
                    title = it.get("title") or ""
                    url = it.get("uri") or it.get("url") or ""
                    snips = it.get("snippets") or []
                    snippet = " ".join(str(s) for s in snips)[:400] if isinstance(snips, list) else str(snips)[:400]
                    lines.append(f"- {title}\n  {url}\n  {snippet}")
                if lines:
                    return "\n".join(lines)
            items = result.get("results") or result.get("items") or []
            if isinstance(items, list) and items:
                lines = []
                for it in items[:top_k]:
                    if isinstance(it, dict):
                        title = it.get("title") or it.get("name") or ""
                        url = it.get("url") or it.get("link") or ""
                        snippet = (it.get("snippet") or it.get("summary")
                                   or it.get("content") or "")
                        lines.append(f"- {title}\n  {url}\n  {str(snippet)[:300]}")
                if lines:
                    return "\n".join(lines)
        import json as _json
        return _json.dumps(result, ensure_ascii=False)[:4000]

    async def stream_chat(self, model: str, messages: list[dict], session_id: str | None = None,
                          tools: list[dict] | None = None, tool_choice=None) -> AsyncIterator[bytes]:
        """Yield raw SSE byte chunks from POST /api/ide/v1/chat."""
        body = self.build_chat_body(model, messages, session_id, tools=tools, tool_choice=tool_choice)
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
