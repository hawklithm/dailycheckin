"""Trae tool-call protocol translation.

Wire protocol (established by live capture, see notes/tooluse-protocol.md and
notes/tooluse-roundtrip-capture.json):

- Tool calls arrive as TEXT embedded in the `output.response` stream:
      <|FunctionCallBegin|>[{"name":"<tool>","parameters":{...}}]<|FunctionCallEnd|>
  The JSON array may contain several calls (parallel invocation). The
  structured `tool_calls` field of the output event stays null.

- Tool results are sent back as PLAIN USER TEXT: the assistant turn keeps the
  raw markup in chat history and the next user message carries the result,
  e.g. "工具执行结果：\\n<result>". OpenAI-style role:function / role:tool
  messages are NOT understood by the gateway (the model re-issues the call).

This module provides:
  ToolCallTranslator      - streaming scanner: Trae markup -> OpenAI tool_calls
  markup_from_tool_calls  - OpenAI tool_calls -> Trae markup (for chat history)
  normalize_messages      - OpenAI message list -> (system_prefix, trae turns)
"""
from __future__ import annotations

import json
import uuid
from typing import Any

BEGIN = "<|FunctionCallBegin|>"
END = "<|FunctionCallEnd|>"


def _partial_marker_tail(buffer: str, marker: str) -> int:
    """Length of the buffer suffix that is a proper prefix of marker (0 if none)."""
    max_check = min(len(buffer), len(marker) - 1)
    for length in range(max_check, 0, -1):
        if marker.startswith(buffer[-length:]):
            return length
    return 0


class ToolCallTranslator:
    """Streaming scanner converting Trae function-call markup into OpenAI deltas.

    feed() returns (plain_text, tool_calls) for each chunk; finish() flushes
    any buffered remainder when the stream ends.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.in_call = False
        self.call_buffer = ""
        self.emitted: list[dict] = []

    def feed(self, text: str) -> tuple[str, list[dict]]:
        out_text: list[str] = []
        out_calls: list[dict] = []
        self.buffer += text
        while True:
            if not self.in_call:
                i = self.buffer.find(BEGIN)
                if i == -1:
                    keep = _partial_marker_tail(self.buffer, BEGIN)
                    if keep:
                        emit, self.buffer = self.buffer[:-keep], self.buffer[-keep:]
                    else:
                        emit, self.buffer = self.buffer, ""
                    if emit:
                        out_text.append(emit)
                    break
                if i > 0:
                    out_text.append(self.buffer[:i])
                self.buffer = self.buffer[i + len(BEGIN):]
                self.in_call = True
                self.call_buffer = ""
            else:
                j = self.buffer.find(END)
                if j == -1:
                    break  # wait for the closing marker
                self.call_buffer += self.buffer[:j]
                self.buffer = self.buffer[j + len(END):]
                self.in_call = False
                calls, raw_ok = self._parse_calls(self.call_buffer)
                if raw_ok:
                    for item in calls:
                        tc = self._to_openai(item)
                        if tc:
                            out_calls.append(tc)
                            self.emitted.append(tc)
                else:
                    # unparseable payload: keep the original bytes losslessly
                    out_text.append(f"{BEGIN}{self.call_buffer}{END}")
                self.call_buffer = ""
        return "".join(out_text), out_calls

    def finish(self) -> tuple[str, list[dict]]:
        """Flush at end of stream. Returns (residual_text, tool_calls)."""
        out_calls: list[dict] = []
        if self.in_call:
            # truncated call: surface raw so nothing is lost
            text = f"{BEGIN}{self.call_buffer}{self.buffer}"
            self.buffer, self.call_buffer, self.in_call = "", "", False
            return text, out_calls
        text, self.buffer = self.buffer, ""
        return text, out_calls

    @staticmethod
    def _parse_calls(payload: str) -> tuple[list[dict], bool]:
        try:
            data = json.loads(payload.strip())
        except json.JSONDecodeError:
            return [], False
        if not isinstance(data, list):
            data = [data]
        return data, True

    def _to_openai(self, item: dict) -> dict | None:
        if not isinstance(item, dict) or not item.get("name"):
            return None
        params = item.get("parameters")
        args = json.dumps(params if params is not None else {}, ensure_ascii=False)
        return {
            "index": len(self.emitted) + len([1]) - 1,  # set by caller order below
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {"name": item["name"], "arguments": args},
        }


def markup_from_tool_calls(tool_calls: list[dict]) -> str:
    """Rebuild Trae markup from OpenAI assistant.tool_calls (for chat history)."""
    items = []
    for tc in tool_calls or []:
        fn = tc.get("function") or {}
        raw_args = fn.get("arguments") or "{}"
        try:
            params = json.loads(raw_args)
        except json.JSONDecodeError:
            params = {"_raw": raw_args}
        items.append({"name": fn.get("name", ""), "parameters": params})
    return f"{BEGIN}{json.dumps(items, ensure_ascii=False)}{END}"


def normalize_messages(messages: list[dict]) -> list[tuple[str, str]]:
    """OpenAI messages -> Trae turns.

    Returns a list of (kind, content) where kind is one of
    system / user / assistant / tool_result. Consecutive tool results are kept
    as separate tool_result turns; the caller merges them into user text.
    """
    turns: list[tuple[str, str]] = []
    for m in messages or []:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        content = "" if content is None else str(content)
        if role == "system":
            turns.append(("system", content))
        elif role == "user":
            turns.append(("user", content))
        elif role == "assistant":
            tcs = m.get("tool_calls") or []
            if tcs:
                markup = markup_from_tool_calls(tcs)
                turns.append(("assistant", (content + markup) if content else markup))
            else:
                turns.append(("assistant", content))
        elif role == "tool":
            name = m.get("name") or m.get("tool_call_id") or "tool"
            turns.append(("tool_result", f"[{name}]\n{content}"))
        elif role == "function":
            name = m.get("name") or "function"
            turns.append(("tool_result", f"[{name}]\n{content}"))
    return turns


def trae_history_and_input(turns: list[tuple[str, str]]) -> tuple[str, list[dict]]:
    """Turns -> (user_input, chat_history) for the gateway body.

    - system turns are prefixed to the first user turn
    - consecutive tool_result turns merge into one user message
      "工具执行结果：\\n..." (proven accepted by the gateway)
    - user_input is the content of the final user-ish turn
    """
    merged: list[tuple[str, str]] = []
    system_prefix = ""
    first_user_seen = False
    for kind, content in turns:
        if kind == "system":
            system_prefix = (system_prefix + "\n\n" + content).strip() if system_prefix else content
            continue
        if kind == "tool_result":
            if merged and merged[-1][0] == "tool_results":
                merged[-1] = ("tool_results", merged[-1][1] + "\n" + content)
            else:
                merged.append(("tool_results", content))
            continue
        if kind == "user" and not first_user_seen and system_prefix:
            merged.append(("user", f"【系统指令】\n{system_prefix}\n\n{content}"))
            first_user_seen = True
            continue
        merged.append((kind, content))

    history: list[dict] = []
    user_input = ""
    for kind, content in merged:
        if kind == "tool_results":
            text = f"工具执行结果：\n{content}"
            role = "user"
        else:
            text, role = content, kind
        if kind == "user" or kind == "tool_results":
            user_input = text
        history.append({"role": role, "content": text, "type": role})
    if not user_input and history:
        user_input = history[-1]["content"] or "继续"
    if not user_input:
        user_input = "继续"
    return user_input, history
