"""Probe Trae's local RPC port (127.0.0.1:51000) over HTTP/2.

The port speaks HTTP/2 (it answers with a SETTINGS frame). Purpose: find out
whether it is gRPC, and if so which services/methods are exposed - that is the
entry point to the real sidecar -> provider path.
"""
import io
import socket
import sys

import h2.connection
import h2.config
import h2.events

HOST, PORT = "127.0.0.1", 51000
LOG = []


def log(*a):
    LOG.append(" ".join(str(x) for x in a))


def handshake():
    sock = socket.create_connection((HOST, PORT), timeout=6)
    cfg = h2.config.H2Configuration(client_side=True, header_encoding="utf-8")
    conn = h2.connection.H2Connection(config=cfg)
    conn.initiate_connection()
    sock.sendall(conn.data_to_send())
    return sock, conn


def read_events(sock, conn, seconds=4.0):
    sock.settimeout(seconds)
    try:
        data = sock.recv(65536)
    except socket.timeout:
        return []
    if not data:
        return []
    return conn.receive_data(data)


def pump(sock, conn):
    out = conn.data_to_send()
    if out:
        sock.sendall(out)


def main() -> int:
    sock, conn = handshake()
    evs = read_events(sock, conn)
    for e in evs:
        if isinstance(e, h2.events.SettingsAcknowledged):
            log("SETTINGS ack")
        elif isinstance(e, h2.events.RemoteSettingsChanged):
            log("remote settings:", e.changed_settings)
        elif isinstance(e, h2.events.WindowUpdated):
            log("window updated", e.stream_id, e.delta)
        else:
            log("event:", type(e).__name__)

    # Try a few plausible gRPC paths. An unknown path yields a normal HTTP/2
    # 404 (or a grpc "unimplemented" status), which still proves gRPC.
    paths = [
        "/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo",
        "/icube.ai_agent.AiAgent/Chat",
        "/aiagent.AiAgent/Chat",
        "/chat.ChatService/Chat",
        "/",
    ]
    for i, path in enumerate(paths, start=1):
        sid = conn.get_next_available_stream_id()
        try:
            conn.send_headers(sid, [
                (":method", "POST"),
                (":scheme", "http"),
                (":authority", f"{HOST}:{PORT}"),
                (":path", path),
                ("content-type", "application/grpc"),
                ("te", "trailers"),
                ("user-agent", "grpc-python-probe/1.0"),
            ], end_stream=True)
            pump(sock, conn)
            evs = read_events(sock, conn, seconds=3.0)
            got = []
            for e in evs:
                if isinstance(e, h2.events.ResponseReceived):
                    hdrs = dict(e.headers)
                    got.append(f"status={hdrs.get(':status')} "
                               f"ct={hdrs.get('content-type')}")
                elif isinstance(e, h2.events.DataReceived):
                    got.append(f"data={e.data[:120]!r}")
                    conn.acknowledge_received_data(e.flow_controlled_length, e.stream_id)
                elif isinstance(e, h2.events.TrailersReceived):
                    got.append(f"trailers={dict(e.headers)}")
                elif isinstance(e, h2.events.StreamReset):
                    got.append(f"reset={e.error_code}")
            log(f"\n[{path}]")
            for g in got:
                log("   " + g)
            if not got:
                log("   (no response within 3s)")
        except Exception as e:  # noqa: BLE001
            log(f"\n[{path}] error: {type(e).__name__}: {e}")
        pump(sock, conn)

    sock.close()
    io.open("logs/_rpc_probe.txt", "w", encoding="utf-8").write("\n".join(LOG))
    print("\n".join(LOG))
    return 0


if __name__ == "__main__":
    sys.exit(main())
