"""Shared fixtures for the trajectory suite: synthetic manifests, a scripted episode driver,
a network-forbidding LLM fake, and fixture scope descriptors for POV projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from saasworld.kernel import Kernel
from saasworld.state.store import WorldState
from saasworld.trajectory.store import open_run


def make_manifest(run_id: str = "run-0001", **overrides: Any) -> dict[str, Any]:
    """A synthetic manifest — every field is caller-provided provenance, nothing computed here."""
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "scenario_id": "onboarding-week",
        "scenario_archetype": "pm_first_week",
        "instance_hash": "inst-abc",
        "action_space_version": "v1",
        "dataset_version": "ds-777",
        "seed": 42,
        "agent_version": "agent-1",
        "sim_t0": 0,
        "started_at_seq": 0,
        "llm_models": {"npc_parser": "claude-sonnet-5", "evaluator": "claude-sonnet-5"},
    }
    manifest.update(overrides)
    return manifest


class ForbiddenLLM:
    """Any invocation fails the test — proves scripted-episode replay makes zero model calls."""

    def __call__(self, record: dict[str, Any]) -> Any:
        raise AssertionError("replay must not call a model")


# A fixed scripted episode: (sim_time, actor, kind, deltas). No LLM-touching kinds.
SCRIPT: list[tuple[int, str, str, list[dict[str, Any]]]] = [
    (0, "agent", "create_task",
     [{"op": "set", "path": "tasks.t1.status", "value": "todo"},
      {"op": "set", "path": "tasks.t1.title", "value": "Payments API"}]),
    (0, "agent", "send_message",
     [{"op": "append", "path": "chat.checkout.log", "value": "status?"},
      {"op": "append", "path": "messages", "value": {"to": "chan.checkout", "body": "status?"}}]),
    (30, "system", "reveal",
     [{"op": "set", "path": "blockers.b1.surfaced", "value": True}]),
    (30, "agent", "update_task",
     [{"op": "set", "path": "tasks.t1.status", "value": "in_progress"}]),
    (60, "npc.fe_a1", "reply",
     [{"op": "append", "path": "chat.checkout.log", "value": "on it"}]),
]

# sim_times treated as eval checkpoints (snapshot cadence) in the scripted episode.
CHECKPOINTS = frozenset({30})
SCORE: dict[str, Any] = {"total": 0.8, "checkpoints": {"triage": 0.9, "comms": 0.7}}


def run_episode(base_dir: Path, manifest: dict[str, Any] | None = None) -> str:
    """Drive SCRIPT through a Kernel with an attached store; snapshot at checkpoints + close."""
    manifest = manifest or make_manifest()
    world = WorldState({"tasks": {}, "chat": {}, "blockers": {}, "messages": []})
    kernel = Kernel(world)
    store = open_run(manifest, state=world, base_dir=base_dir)
    kernel.add_sink(store.record)
    seen: set[int] = set()
    for sim_time, actor, kind, deltas in SCRIPT:
        kernel.schedule(sim_time, actor, kind, {"deltas": deltas})
        kernel.advance_until(sim_time)
        if sim_time in CHECKPOINTS and sim_time not in seen:
            store.snapshot(store.last_seq, sim_time, world)
            seen.add(sim_time)
    store.close_run(SCORE)
    return str(manifest["run_id"])


@pytest.fixture
def episode(tmp_path: Path) -> tuple[str, Path]:
    """A persisted scripted run under tmp_path (repo never polluted). Returns (run_id, base_dir)."""
    base_dir = tmp_path / "runs"
    return run_episode(base_dir), base_dir


@pytest.fixture
def scopes() -> dict[str, dict[str, list[str]]]:
    """Synthetic per-actor view scopes (real persona view_scopes plug into the same shape)."""
    return {
        "agent": {"paths": ["tasks", "chat", "messages"], "actors": ["agent"]},
        "npc.fe_a1": {"paths": ["chat"], "actors": ["npc.fe_a1"]},
        "grader": {"paths": ["tasks", "blockers"], "actors": []},
    }
