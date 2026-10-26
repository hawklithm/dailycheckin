"""Bisect the llm_raw_chat request body.

The endpoint returns 4001 (param invalid) rather than 404, so it exists and our
auth works. Strategy: start from the shape convertReqToRustPayload builds and
strip down until the error changes - each change of error message is a signal.

Also try the model_list endpoint with progressively richer bodies.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from trae2api.auth import TraeAuth  # noqa: E402
from trae2api.gateway import TraeGateway  # noqa: E402

OUT: list[str] = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


async def main() -> int:
    auth = TraeAuth()
    auth.load()
    gw = TraeGateway(auth)

    async def post(path, body):
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{gw.base}{path}", json=body, headers=gw._headers())
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text[:300]

    # ---- model_list variants ----
    log("=== model_list variants ===")
    variants = [
        ("empty", {}),
        ("only user_info", {"user_info": {"user_id": "3481484447459108"}}),
        ("only common_params", {"common_params": {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"}}),
        ("service=model", {"service": "model", "method": "get_model_list"}),
        ("data-only", {"data": {}}),
        ("full", {
            "service": "model", "method": "get_model_list",
            "user_info": {"user_id": "3481484447459108", "user_type": "user",
                          "user_is_login": True},
            "common_params": {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                              "app_name": "trae", "region": "CN"},
            "client_info": {"client_type": "ide", "device_id": "4333646823299987"},
        }),
        ("full+data", {
            "service": "model", "method": "get_model_list",
            "data": {"function_type": "chat", "chat_type": "builder"},
            "user_info": {"user_id": "3481484447459108", "user_type": "user",
                          "user_is_login": True},
            "common_params": {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                              "app_name": "trae", "region": "CN"},
            "client_info": {"client_type": "ide", "device_id": "4333646823299987"},
        }),
    ]
    for label, body in variants:
        code, resp = await post("/api/ide/v1/model_list", body)
        s = json.dumps(resp, ensure_ascii=False)[:220]
        log(f"  [{label}] {code} {s}")

    # ---- llm_raw_chat variants ----
    log("\n=== llm_raw_chat variants ===")
    base = {
        "service": "chat", "method": "chat",
        "user_info": {"user_id": "3481484447459108", "user_type": "user",
                      "user_is_login": True, "device_id": "4333646823299987"},
        "common_params": {"app_id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                          "app_name": "trae", "region": "CN", "agent_type": "builder"},
        "client_info": {"client_type": "ide", "device_id": "4333646823299987",
                        "icube_language": "zh-CN"},
    }
    chat_variants = [
        ("no data", dict(base)),
        ("data minimal", {**base, "data": {"user_input": "hi"}}),
        ("data + message_content", {**base, "data": {
            "user_input": "hi",
            "message_content": [{"type": "text", "text_content": "hi"}]}}),
        ("data + model_name auto", {**base, "data": {
            "user_input": "hi",
            "message_content": [{"type": "text", "text_content": "hi"}],
            "model_name": "auto"}}),
        ("data + agent_type/scene", {**base, "data": {
            "user_input": "hi",
            "message_content": [{"type": "text", "text_content": "hi"}],
            "model_name": "auto",
            "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder", "title": "Builder"}}}),
        ("v1 path", {**base, "data": {
            "user_input": "hi",
            "message_content": [{"type": "text", "text_content": "hi"}],
            "model_name": "auto", "agent_type": "builder", "scene_location": 2,
            "agent": {"type": "builder", "name": "builder", "title": "Builder"}}}),
    ]
    for label, body in chat_variants:
        path = "/api/ide/v1/llm_raw_chat" if label == "v1 path" else "/api/ide/v2/llm_raw_chat"
        code, resp = await post(path, body)
        s = json.dumps(resp, ensure_ascii=False)[:260] if not isinstance(resp, str) else resp[:260]
        log(f"  [{label}] {path} -> {code} {s}")

    io.open("logs/_bisect.txt", "w", encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
