"""Server-side environment: wraps the live Kernel + WorldState behind an OpenEnv-shaped API.

`reset(scenario)` seeds a fresh world from a frozen instance (or a bare `data/scenarios/` name),
`step(action)` drives one Tool-API verb through the single-writer kernel, and `state` reports
episode metadata. Reward is **terminal**: `None` every step until the sim clock crosses the last
eval checkpoint, then the deterministic Evaluator's final score — with the full weighted breakdown
in `observation.metadata["score"]`. The trajectory scored at `done` is reconstructed in-memory from
the same `(event, applied_delta)` stream the Trajectory Store persists, so the score matches
`saasworld run-eval` exactly.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from saasworld.actions.catalog import load_catalog
from saasworld.api.rpc import dispatch
from saasworld.eval.score import score
from saasworld.events import Event
from saasworld.kernel import Kernel
from saasworld.scenario.loader import load as scenario_load
from saasworld.scenario.loader import offset_to_minutes
from saasworld.state.store import WorldState

from .types import SaasWorldAction, SaasWorldObservation, State

_CATALOG = Path(__file__).resolve().parents[3] / "data" / "actions.json"


def _at_minutes(at: Any) -> int:
    """A checkpoint `at` is either sim-minutes or a `D<day>T<HH:MM>` offset."""
    return at if isinstance(at, int) else offset_to_minutes(str(at))


class SaasWorldEnvironment:
    """A single episode over one Kernel/WorldState. One writer, one session — the repo's stance."""

    def __init__(self) -> None:
        self._catalog = load_catalog(_CATALOG)
        self._kernel: Kernel | None = None
        self._world: WorldState | None = None
        self._events: list[tuple[Event, list[dict[str, Any]]]] = []
        self._opening: dict[str, Any] = {}
        self._ground_truth: dict[str, Any] = {}
        self._horizon = 0
        self._scored = False
        self._state = State()

    # ---- lifecycle ---------------------------------------------------------------------------

    def reset(
        self,
        scenario: str = "checkout-not-ready",
        seed: int | None = None,
        agent_version: str = "baseline",
        episode_id: str | None = None,
        **_: Any,
    ) -> SaasWorldObservation:
        """Seed a fresh world from `scenario` (a `data/scenarios/` name or an instance path)."""
        world = WorldState()
        kernel = Kernel(world)
        loaded = scenario_load(scenario, kernel)

        self._events = []
        kernel.add_sink(lambda e, d: self._events.append((e, d)))  # tap the single-writer stream

        self._kernel, self._world = kernel, world
        self._ground_truth = loaded.eval_ground_truth
        self._horizon = max(
            (_at_minutes(cp["at"]) for cp in self._ground_truth.get("checkpoints", [])),
            default=0,
        )
        self._scored = False
        self._opening = {"seq": 0, "sim_time": kernel.now(), "state": world.snapshot()}
        self._state = State(
            episode_id=episode_id or str(uuid4()), step_count=0,
            run_id=f"{loaded.scenario_id}.{agent_version}.{seed if seed is not None else 0}",
            scenario_id=loaded.scenario_id, sim_time=kernel.now(),
        )
        return SaasWorldObservation(
            done=False, reward=None, sim_time=kernel.now(), state=world.snapshot(),
            events=[], ack=None,
            metadata={"scenario_id": loaded.scenario_id, "horizon": self._horizon,
                      "dataset_version": loaded.dataset_version},
        )

    def step(self, action: SaasWorldAction) -> SaasWorldObservation:
        """Drive one verb through the Tool API; terminal reward once the clock crosses horizon."""
        if self._kernel is None or self._world is None:
            raise RuntimeError("call reset() before step()")
        kernel, world = self._kernel, self._world
        self._state.step_count += 1

        reply = dispatch(kernel, world, self._catalog, "action",
                         {"verb": action.verb, "args": action.args})
        now = kernel.now()
        self._state.sim_time = now

        if "error" in reply:  # invalid/denied action: not terminal, no reward, surfaced in metadata
            return SaasWorldObservation(
                done=self._done(now), reward=None, sim_time=now, state=world.snapshot(),
                events=[], ack=None, metadata={"error": reply["error"]},
            )

        result = reply["result"]
        done = self._done(now)
        reward: float | None = None
        meta: dict[str, Any] = {"step": self._state.step_count}
        if done and not self._scored:  # cross the horizon once -> the deterministic final score
            breakdown = score(self._trajectory(), self._ground_truth)
            reward = breakdown.final
            meta["score"] = asdict(breakdown)
            self._scored = True
        return SaasWorldObservation(
            done=done, reward=reward, sim_time=now, state=world.snapshot(),
            events=result.get("events_since", []), ack=result.get("ack"), metadata=meta,
        )

    @property
    def state(self) -> State:
        return self._state

    def close(self) -> None:
        self._kernel = self._world = None

    # ---- internals ---------------------------------------------------------------------------

    def _done(self, now: int) -> bool:
        return self._horizon > 0 and now >= self._horizon

    def _trajectory(self) -> dict[str, Any]:
        """Opening snapshot + every applied event — the shape the Evaluator scores."""
        return {
            "snapshots": [self._opening],
            "events": [
                {"seq": e.seq, "sim_time": e.sim_time, "actor": e.actor, "kind": e.kind,
                 "payload": {"deltas": d or []}, "caused_by": e.caused_by}
                for e, d in self._events
            ],
        }
