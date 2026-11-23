"""Extract per-handler RPC method tables (corrected: names follow the handler).

Layout discovered by inspecting raw bytes:

    ... apps\\icube_server_rs\\modules\\ai-agent\\src\\handler\\model.rs |
    [ModelHandler] start model handler |
    model_list model_list_by_function connect custom_model_connectivity_check
    update_custom_model add_custom_model providers get_custom_model_type_config
    get_model_selection_modes prefetch_for_auto |
    [ModelHandler] unknown method: |

So the method names sit in the run IMMEDIATELY AFTER the
"[<Handler>] start ... handler" log string, as a concatenated list, and before
the "unknown method" string.

This yields the authoritative RPC surface - the interface a client must call.
"""
from __future__ import annotations

import io
import os
import re
import sys

TRAE = r"D:\Users\marcus\AppData\Local\Programs\Trae CN"
DLL = os.path.join(TRAE, r"resources\app\modules\ai-agent\ai_agent.dll")

OUT: list[str] = []

# words that are log text, not method names
NOISE = {
    "start", "handler", "model", "unknown", "method", "force", "refresh",
    "after", "list", "by", "function", "all", "ready", "is", "for", "ok",
    "the", "of", "and", "not", "available", "database", "cache", "no",
    "message", "incomming", "bug", "this", "apps", "src", "modules",
    "ai", "agent", "handler", "rs", "corrupted", "is", "a",
}


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def split_snake(run: str) -> list[str]:
    """Split a concatenated snake_case run into method names.

    Heuristic: a method name is a lowercase snake_case token. Because they are
    concatenated without separators, we split on the known vocabulary of verbs
    used by this codebase (get_/set_/create_/update_/...).
    """
    parts = re.split(r"(?=(?:get|set|create|update|delete|remove|add|list|"
                     r"batch|prefetch|connect|save|sync|stop|start|send|"
                     r"query|check|report|commit|apply|generate|fetch|"
                     r"register|unregister|install|uninstall|enable|"
                     r"disable|revert|pin|unpin|fork|clean|clear|search|"
                     r"open|close|run|read|write|upload|download|import|"
                     r"export|switch|move|copy|rename|notify|poll|wait|"
                     r"call|cancel|confirm|reject|approve|deny)_)", run)
    out = []
    for p in parts:
        p = p.strip("_")
        if len(p) > 3 and "_" in p and not p.isdigit():
            out.append(p)
    return out


def main() -> int:
    with io.open(DLL, "rb") as f:
        buf = f.read()

    log("=" * 74)
    log("RPC HANDLER METHOD TABLES (from ai_agent.dll)")
    log("=" * 74)

    # find each "src\handler\<name>.rs" then the following handler strings
    src_re = re.compile(
        rb"apps\\icube_server_rs\\modules\\ai-agent\\src\\handler\\"
        rb"([a-z_]+)\.rs")
    results: dict[str, list[str]] = {}

    for m in src_re.finditer(buf):
        module = m.group(1).decode("ascii", "replace")
        # look ahead up to 1200 bytes for "[XHandler] ... handler" then the run
        window = buf[m.end():m.end() + 1200]
        hm = re.search(rb"\[([A-Za-z]+Handler)\][^|]{0,60}handler", window)
        if not hm:
            continue
        handler = hm.group(1).decode("ascii", "replace")
        after = window[hm.end():hm.end() + 600]
        # the method list is the printable run right after, up to 'unknown'
        stop = after.find(b"unknown method")
        seg = after[:stop] if stop > 0 else after[:400]
        txt = re.sub(rb"[^\x20-\x7e]+", b" ", seg).decode("ascii", "replace")
        meths = split_snake(txt)
        if meths:
            results.setdefault(handler, [])
            for x in meths:
                if x not in results[handler]:
                    results[handler].append(x)

    total = 0
    for handler in sorted(results):
        ms = results[handler]
        total += len(ms)
        log(f"\n### {handler}  ({len(ms)} methods)")
        for k in range(0, len(ms), 3):
            log("    " + "  ".join(f"{x:34}" for x in ms[k:k + 3]))
    log(f"\n=== handlers: {len(results)}, methods: {total} ===")

    io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs", "_rpcmethods.txt"), "w",
        encoding="utf-8").write("\n".join(OUT))
    print("\n".join(OUT)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
