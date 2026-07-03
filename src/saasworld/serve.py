"""DEPRECATED entrypoint — the standalone JSON-RPC Tool API server (was :8080).

Superseded by the OpenEnv server (`saasworld-env-serve`, :8092), which is now the single running
service: it drives episodes (`/reset`, `/step`, `/state`) over the same single-writer kernel and
also hosts the trajectory inspector at `/inspector`. Running two servers isn't worth it.

The raw `POST /rpc` transport still exists as an app factory — `saasworld.api.app.create_app` — for
the test suite and the operator CLI's optional `--backend http`. If you truly need the raw RPC
server, run it explicitly; this convenience entrypoint no longer boots one.
"""

from __future__ import annotations

import sys


def main() -> None:
    sys.exit(
        "saasworld-serve is deprecated. Use `saasworld-env-serve` (OpenEnv on :8092) instead —\n"
        "it hosts /reset, /step, /state and the inspector at http://127.0.0.1:8092/inspector.\n"
        "Need the raw JSON-RPC server? Run: "
        "python -c \"import uvicorn; from saasworld.api.app import create_app; "
        "uvicorn.run(create_app(), host='127.0.0.1', port=8080)\""
    )


if __name__ == "__main__":
    main()
