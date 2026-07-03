"""FastAPI server exposing one `SaasWorldEnvironment` over the OpenEnv-shaped HTTP contract.

Routes mirror OpenEnv: `POST /reset`, `POST /step`, `GET /state`, `GET /health`. Every reset/step
returns a `StepResult` envelope (`observation` + `reward` + `done` + `metadata`) so the client
reconstructs it verbatim. One environment instance = one session (single writer), consistent with
the single-node design; run one process per concurrent episode.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from saasworld.api.inspector import router as inspector_router

from .environment import SaasWorldEnvironment
from .types import SaasWorldAction, SaasWorldObservation, StepResult


def _envelope(obs: SaasWorldObservation) -> dict[str, Any]:
    return StepResult(obs, reward=obs.reward, done=obs.done, metadata=obs.metadata).to_dict()


def create_env_app(env: SaasWorldEnvironment | None = None) -> FastAPI:
    """Build the env server around `env` (a fresh one by default)."""
    environment = env or SaasWorldEnvironment()
    app = FastAPI(title="saas-world OpenEnv environment")
    app.state.env = environment  # exposed for tests
    app.include_router(inspector_router)  # read-only trajectory inspector UI over runs/

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/reset")
    async def reset(request: Request) -> dict[str, Any]:
        body = await request.json()
        return _envelope(environment.reset(**(body or {})))

    @app.post("/step")
    async def step(request: Request) -> dict[str, Any]:
        body = await request.json()
        action = body.get("action", body) if isinstance(body, dict) else {}
        return _envelope(environment.step(SaasWorldAction.from_dict(action)))

    @app.get("/state")
    def state() -> dict[str, Any]:
        return environment.state.to_dict()

    @app.get("/trajectory")
    def trajectory() -> dict[str, Any]:
        """Canonical event log (opening snapshot + events w/ deltas) for replay/timeline tools."""
        return environment.canonical_trajectory()

    return app
