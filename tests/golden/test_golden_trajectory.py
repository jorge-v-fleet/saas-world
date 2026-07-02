"""Determinism: a fixed episode persists a trajectory + final snapshot byte-identical to a golden.

The scripted episode is driven through the Kernel with the Trajectory Store attached; the persisted
``trajectory.jsonl`` and final snapshot are asserted byte-for-byte against a stored golden, and a
second run replays to the same bytes. Regenerate with ``pytest --update-golden``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from saasworld.kernel import Kernel
from saasworld.state.store import WorldState
from saasworld.trajectory.replay import replay
from saasworld.trajectory.store import open_run

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).parent / "trajectory_episode.json"

MANIFEST: dict[str, Any] = {
    "run_id": "golden-run",
    "scenario_id": "onboarding-week",
    "scenario_archetype": "pm_first_week",
    "instance_hash": "inst-golden",
    "action_space_version": "v1",
    "dataset_version": "ds-golden",
    "seed": 1,
    "agent_version": "agent-golden",
    "sim_t0": 0,
    "started_at_seq": 0,
    "llm_models": {"npc_parser": "claude-sonnet-5", "evaluator": "claude-sonnet-5"},
}

SCRIPT = [
    (0, "agent", "create_task", [{"op": "set", "path": "tasks.t1.status", "value": "todo"}]),
    (0, "agent", "send_message",
     [{"op": "append", "path": "chat.checkout.log", "value": "status?"}]),
    (30, "system", "reveal", [{"op": "set", "path": "blockers.b1.surfaced", "value": True}]),
    (30, "agent", "update_task",
     [{"op": "set", "path": "tasks.t1.status", "value": "in_progress"}]),
]
SCORE = {"total": 0.8, "checkpoints": {"triage": 0.9, "comms": 0.7}}


def _run(base_dir: Path) -> tuple[str, dict[str, Any]]:
    """Drive SCRIPT with the store attached; return the trajectory text + final snapshot."""
    world = WorldState({"tasks": {}, "chat": {}, "blockers": {}})
    kernel = Kernel(world)
    store = open_run(MANIFEST, state=world, base_dir=base_dir)
    kernel.add_sink(store.record)
    for sim_time, actor, kind, deltas in SCRIPT:
        kernel.schedule(sim_time, actor, kind, {"deltas": deltas})
        kernel.advance_until(sim_time)
    store.close_run(SCORE)
    run_id = str(MANIFEST["run_id"])
    text = (base_dir / run_id / "trajectory.jsonl").read_text()
    final = replay(run_id, base_dir).final_state
    return text, final


def _canonical(trajectory: str, final: dict[str, Any]) -> str:
    return json.dumps({"trajectory": trajectory, "final": final}, sort_keys=True, indent=2)


def test_trajectory_matches_golden(tmp_path: Path, update_golden: bool) -> None:
    text = _canonical(*_run(tmp_path / "runs"))
    if update_golden:
        GOLDEN.write_text(text + "\n")
        return
    assert text + "\n" == GOLDEN.read_text()


def test_replay_is_byte_identical(tmp_path: Path) -> None:
    a = _canonical(*_run(tmp_path / "runs_a"))
    b = _canonical(*_run(tmp_path / "runs_b"))
    assert a == b
