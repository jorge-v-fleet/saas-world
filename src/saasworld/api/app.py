"""FastAPI app exposing the Tool API over JSON-RPC.

Holds a single Kernel + WorldState; requests are serialized through the kernel so single-writer
ordering is preserved. `POST /rpc` for actions, `GET /health` for liveness.
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the app with a fresh bootstrapped world."""
    raise NotImplementedError
