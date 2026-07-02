"""OpenEnv-shaped SDK for saas-world.

Native (no `openenv` dependency): the same Action / Observation / State / StepResult contract and
`reset` / `step` / `state` methods as Hugging Face OpenEnv, so an agent written against OpenEnv
drops onto saas-world. Server and client are decoupled over HTTP.

    from saasworld.openenv import SaasWorldEnv, SaasWorldAction
    with SaasWorldEnv("http://127.0.0.1:8092") as env:
        res = env.reset(scenario="checkout-not-ready")
        res = env.step(SaasWorldAction("send_message", {"to": "org.be_b2", "body": "...",
                                                        "refs": ["task.psp_integration"]}))
"""

from __future__ import annotations

from .client import SaasWorldEnv
from .environment import SaasWorldEnvironment
from .server import create_env_app
from .types import SaasWorldAction, SaasWorldObservation, State, StepResult

__all__ = [
    "SaasWorldEnv", "SaasWorldEnvironment", "create_env_app",
    "SaasWorldAction", "SaasWorldObservation", "State", "StepResult",
]
