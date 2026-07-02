"""A driven episode persists, replays byte-for-byte, and surfaces in the derived index."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from saasworld.kernel import Kernel
from saasworld.state.store import WorldState
from saasworld.trajectory.index import TrajectoryIndex
from saasworld.trajectory.project import project
from saasworld.trajectory.replay import replay
from saasworld.trajectory.store import open_run

pytestmark = pytest.mark.integration

MANIFEST: dict[str, Any] = {
    "run_id": "run-int",
    "scenario_id": "onboarding-week",
    "scenario_archetype": "pm_first_week",
    "instance_hash": "inst-int",
    "action_space_version": "v1",
    "dataset_version": "ds-int",
    "seed": 7,
    "agent_version": "agent-int",
    "sim_t0": 0,
    "started_at_seq": 0,
    "llm_models": {"npc_parser": "claude-sonnet-5", "evaluator": "claude-sonnet-5"},
}

EPISODE = [
    (0, "agent", "create_task", [{"op": "set", "path": "tasks.t1.status", "value": "todo"}]),
    (0, "agent", "send_message", [{"op": "append", "path": "chat.c.log", "value": "hi"}]),
    (30, "system", "reveal", [{"op": "set", "path": "blockers.b1.surfaced", "value": True}]),
    (30, "agent", "update_task", [{"op": "set", "path": "tasks.t1.status", "value": "done"}]),
]
SCORE = {"total": 0.75, "checkpoints": {"triage": 0.8, "comms": 0.7}}


def _drive(base_dir: Path) -> str:
    world = WorldState({"tasks": {}, "chat": {}, "blockers": {}})
    kernel = Kernel(world)
    store = open_run(MANIFEST, state=world, base_dir=base_dir)
    kernel.add_sink(store.record)
    for sim_time, actor, kind, deltas in EPISODE:
        kernel.schedule(sim_time, actor, kind, {"deltas": deltas})
        kernel.advance_until(sim_time)
    store.close_run(SCORE)
    return str(MANIFEST["run_id"])


def test_persist_replay_and_index(tmp_path: Path) -> None:
    base = tmp_path / "runs"
    run_id = _drive(base)

    # replay reproduces the on-disk log byte-for-byte + the final snapshot, with no model calls
    raw = (base / run_id / "trajectory.jsonl").read_text()
    result = replay(run_id, base)
    assert result.event_log == raw
    assert result.model_calls == 0
    final_snap = json.loads(sorted((base / run_id / "snapshots").glob("*.json"))[-1].read_text())
    assert result.final_state == final_snap["state"]

    # the derived index finds the run
    idx = TrajectoryIndex(tmp_path / "index.duckdb")
    idx.rebuild(base)
    rows = idx.sql("SELECT * FROM runs")
    assert len(rows) == 1 and rows[0]["run_id"] == run_id
    assert rows[0]["total"] == 0.75
    idx.close()

    # grader projection derivation equals the appended score record
    view = project(run_id, "grader", at=30, scopes={"grader": {"paths": ["tasks"], "actors": []}},
                   base_dir=base)
    assert view.extras["score"] == SCORE
