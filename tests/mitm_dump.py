"""mitmproxy addon: dump every request/response touching the Trae gateway.

Saves full bodies so we can read the exact llm_raw_chat / model_list request
the sidecar sends. Run with:

  set PYTHONPATH=D:\\workspace\\trae2api\\.mitm
  mitmdump -s tests\\mitm_dump.py --set confdir=D:\\mitmconf -w D:\\trae.flow
"""
from __future__ import annotations

import io
import json
import os
import time

INTERESTING = (
    "trae-api-cn.mchost.guru",
    "api.trae.cn",
    "api.trae.com.cn",
    "marscode.cn",
    "byteintl",
    "volces",
)

OUT = os.environ.get("MITM_OUT", r"D:\workspace\trae2api\logs\mitm-requests.jsonl")


def _keep(host: str) -> bool:
    return any(h in host for h in INTERESTING)


def _body(flow) -> str:
    try:
        raw = flow.request.get_content(strict=False)
    except Exception:
        return ""
    if not raw:
        return ""
    if len(raw) > 400_000:
        return f"<{len(raw)} bytes omitted>"
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", "replace")


def request(flow) -> None:
    host = flow.request.pretty_host
    if not _keep(host):
        return
    rec = {
        "ts": time.time(),
        "kind": "request",
        "method": flow.request.method,
        "url": flow.request.url,
        "host": host,
        "path": flow.request.path,
        "headers": dict(flow.request.headers),
        "body": _body(flow),
    }
    with io.open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[REQ] {flow.request.method} {host}{flow.request.path} "
          f"({len(rec['body'])}b)", flush=True)


def response(flow) -> None:
    host = flow.request.pretty_host
    if not _keep(host):
        return
    try:
        raw = flow.response.get_content(strict=False) or b""
    except Exception:
        raw = b""
    if len(raw) > 400_000:
        body = f"<{len(raw)} bytes omitted>"
    else:
        try:
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            body = raw.decode("latin-1", "replace")
    rec = {
        "ts": time.time(),
        "kind": "response",
        "status": flow.response.status_code,
        "url": flow.request.url,
        "host": host,
        "path": flow.request.path,
        "headers": dict(flow.response.headers),
        "body": body,
    }
    with io.open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[RSP] {flow.response.status_code} {host}{flow.request.path} "
          f"({len(body)}b)", flush=True)
