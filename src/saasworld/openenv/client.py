"""Client SDK — talks to a running env server over plain HTTP (stdlib only).

`reset()` / `step()` return a `StepResult`; `state()` returns `State`. This is the surface an agent
loop drives:

    with SaasWorldEnv("http://127.0.0.1:8092") as env:
        res = env.reset(scenario="checkout-not-ready")
        while not res.done:
            res = env.step(SaasWorldAction(verb="send_message", args={...}))
        print(res.reward)   # deterministic evaluator final at end-of-week
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from .types import SaasWorldAction, State, StepResult

_DEFAULT_URL = "http://127.0.0.1:8092"


class SaasWorldEnv:
    """Decoupled client for a `saasworld.openenv` server process."""

    def __init__(self, base_url: str = _DEFAULT_URL, timeout_s: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    def reset(self, scenario: str = "checkout-not-ready", **kwargs: Any) -> StepResult:
        return StepResult.from_dict(self._post("/reset", {"scenario": scenario, **kwargs}))

    def step(self, action: SaasWorldAction | dict[str, Any]) -> StepResult:
        payload = action.to_dict() if isinstance(action, SaasWorldAction) else action
        return StepResult.from_dict(self._post("/step", {"action": payload}))

    def state(self) -> State:
        return State.from_dict(self._get("/state"))

    def trajectory(self) -> dict[str, Any]:
        """Canonical event log (opening snapshot + events w/ deltas) — for replay/timeline tools."""
        return self._get("/trajectory")

    def health(self) -> bool:
        try:
            return self._get("/health").get("status") == "ok"
        except OSError:
            return False

    def close(self) -> None:  # nothing to release: stateless HTTP client
        pass

    def __enter__(self) -> SaasWorldEnv:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ---- transport ---------------------------------------------------------------------------

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self._base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        return self._send(req)

    def _get(self, path: str) -> dict[str, Any]:
        return self._send(urllib.request.Request(self._base + path))

    def _send(self, req: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 - local operator endpoint
                data: dict[str, Any] = json.loads(resp.read())
        except OSError as e:
            raise ConnectionError(f"env server unreachable at {self._base}: {e}") from e
        return data
