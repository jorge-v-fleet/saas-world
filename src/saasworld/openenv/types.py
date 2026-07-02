"""OpenEnv-shaped SDK types — native, no `openenv` dependency.

Mirrors Hugging Face OpenEnv's core contract *by shape*: `Action` / `Observation` / `State` /
`StepResult` carry the same fields and semantics, so an agent loop written against OpenEnv reads
identically here. Plain stdlib dataclasses (no pydantic) keep the SDK dependency-free; every type
round-trips through `to_dict` / `from_dict` for the HTTP wire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SaasWorldAction:
    """One PM tool call: a catalog `verb` plus its `args` (the Tool API, one action type)."""

    verb: str
    args: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"verb": self.verb, "args": self.args, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SaasWorldAction:
        return cls(verb=d["verb"], args=d.get("args") or {}, metadata=d.get("metadata") or {})


@dataclass
class SaasWorldObservation:
    """The agent's view after a step. `done` / `reward` / `metadata` mirror OpenEnv.Observation;
    the rest is the saas-world surface (world snapshot, events this step, sim clock, last ack)."""

    done: bool = False
    reward: float | None = None
    sim_time: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    ack: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "done": self.done, "reward": self.reward, "sim_time": self.sim_time,
            "state": self.state, "events": self.events, "ack": self.ack,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SaasWorldObservation:
        return cls(
            done=bool(d.get("done", False)), reward=d.get("reward"),
            sim_time=int(d.get("sim_time", 0)), state=d.get("state") or {},
            events=d.get("events") or [], ack=d.get("ack"), metadata=d.get("metadata") or {},
        )


@dataclass
class State:
    """Episode metadata, OpenEnv.State-shaped (`episode_id` + `step_count`) plus run identity."""

    episode_id: str | None = None
    step_count: int = 0
    run_id: str | None = None
    scenario_id: str | None = None
    sim_time: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id, "step_count": self.step_count,
            "run_id": self.run_id, "scenario_id": self.scenario_id, "sim_time": self.sim_time,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> State:
        return cls(
            episode_id=d.get("episode_id"), step_count=int(d.get("step_count", 0)),
            run_id=d.get("run_id"), scenario_id=d.get("scenario_id"),
            sim_time=int(d.get("sim_time", 0)),
        )


@dataclass
class StepResult:
    """The value `reset()` / `step()` return — OpenEnv.StepResult by shape."""

    observation: SaasWorldObservation
    reward: float | None = None
    done: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.to_dict(), "reward": self.reward,
            "done": self.done, "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StepResult:
        return cls(
            observation=SaasWorldObservation.from_dict(d.get("observation") or {}),
            reward=d.get("reward"), done=bool(d.get("done", False)),
            metadata=d.get("metadata") or {},
        )
