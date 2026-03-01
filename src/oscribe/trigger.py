from __future__ import annotations

import os

import zmq


def _ipc_address() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return f"ipc://{runtime}/oscribe.ipc"
    return "ipc:///tmp/oscribe_service.ipc"


IPC_ADDRESS = _ipc_address()


def main() -> None:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect(IPC_ADDRESS)
    sock.setsockopt(zmq.RCVTIMEO, 2000)

    sock.send_string("TOGGLE")
    try:
        reply = sock.recv_string()
        print(f"Service replied: {reply}")
    except zmq.error.Again:
        print("Service timed out. Is oscribe running?")

    sock.close()
    ctx.term()


if __name__ == "__main__":
    main()
