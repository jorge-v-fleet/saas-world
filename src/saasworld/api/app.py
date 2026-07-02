"""FastAPI app exposing the Tool API over JSON-RPC.

Holds a single Kernel + WorldState; requests are serialized through the kernel so single-writer
ordering is preserved. `POST /rpc` for actions, `GET /health` for liveness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

from saasworld.actions.catalog import load_catalog
from saasworld.api.rpc import dispatch
from saasworld.bootstrap import load_bootstrap
from saasworld.kernel import Kernel
from saasworld.state.store import WorldState

_CATALOG = Path(__file__).parents[3] / "data" / "actions.json"


def create_app() -> FastAPI:
    """Build the app with a fresh bootstrapped world behind one Kernel (single writer)."""
    world = WorldState(load_bootstrap())
    kernel = Kernel(world)
    catalog = load_catalog(_CATALOG)

    app = FastAPI()
    app.state.kernel = kernel  # exposed for operator tests (e.g. pre-scheduling system events)
    app.state.world = world
    app.state.catalog = catalog

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/rpc")
    async def rpc(request: Request) -> dict[str, Any]:
        body = await request.json()
        result = dispatch(kernel, world, catalog, body.get("method"), body.get("params") or {})
        return {"jsonrpc": "2.0", "id": body.get("id"), **result}

    return app
