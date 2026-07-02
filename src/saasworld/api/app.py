"""FastAPI app holding ONE Kernel + WorldState (single writer, one worker).

Wire in create_app():
  - state = WorldState(load_bootstrap(...))
  - kernel = Kernel(state)
  - catalog = load_catalog(data/actions.json)
  - POST /rpc  -> rpc.dispatch(kernel, state, catalog, method, params); serialize requests
                   through the kernel (a lock) to preserve single-writer determinism.
  - GET  /health -> {"ok": true}
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the app with a fresh bootstrapped world."""
    raise NotImplementedError
