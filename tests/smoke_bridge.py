"""Static sanity check: import the server module and call the bridge generator
far enough to prove the NameError is gone (it fails at the first SSE round,
which is fine - we only care that it starts)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["TRAE2API_DEBUG"] = "0"


async def main() -> None:
    from trae2api import server
    from trae2api.auth import TraeAuth

    server.auth.load()
    from trae2api.gateway import TraeGateway
    server.gateway = TraeGateway(server.auth)

    # the bridge used to raise NameError: name 'body' is not defined
    # before ever contacting the gateway. Starting it proves the fix.
    gen = server._bridge_events(
        "x",
        [{"role": "user", "content": "ping"}],
        [{"type": "function", "function": {"name": "read", "description": "d",
          "parameters": {"type": "object", "properties": {}}}}],
        {"read"},
        tool_choice=None,
    )
    got = 0
    try:
        async for _ in gen:
            got += 1
            if got >= 3:
                break
    except Exception as e:  # noqa: BLE001
        # a gateway/network error is acceptable here; a NameError is not
        if "NameError" in type(e).__name__ or "not defined" in str(e):
            print("FAIL: still undefined ->", e)
            return 1
        print("ok: no NameError (stopped at:", type(e).__name__, str(e)[:80], ")")
        return 0
    print(f"ok: bridge streamed {got} events without NameError")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
