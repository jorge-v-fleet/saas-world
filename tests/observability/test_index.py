"""Cross-run index: derivation, the three named analyses, and full rebuildability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from saasworld.kernel import Kernel
from saasworld.state.store import WorldState
from saasworld.trajectory.index import TrajectoryIndex
from saasworld.trajectory.store import open_run

from .conftest import make_manifest

pytestmark = pytest.mark.observability

Event = tuple[int, str, str, list[dict[str, Any]]]


def build_run(
    base_dir: Path, manifest: dict[str, Any], events: list[Event], score: dict[str, Any]
) -> None:
    """Persist a synthetic run: drive `events` through a Kernel + attached store, then close."""
    world = WorldState({"tasks": {}, "chat": {}, "blockers": {}, "messages": []})
    kernel = Kernel(world)
    store = open_run(manifest, state=world, base_dir=base_dir)
    kernel.add_sink(store.record)
    for sim_time, actor, kind, deltas in events:
        kernel.schedule(sim_time, actor, kind, {"deltas": deltas})
        kernel.advance_until(sim_time)
    store.close_run(score)


def _real_work(t: int) -> Event:
    return (t, "agent", "update_task", [{"op": "set", "path": "tasks.t1.status", "value": "done"}])


def _message(t: int) -> Event:
    return (t, "agent", "send_message",
            [{"op": "append", "path": "chat.c.log", "value": "hi"}])


@pytest.fixture
def seeded_runs(tmp_path: Path) -> Path:
    """A runs/ dir spanning agent versions, a failure, and a reward-hack run."""
    base = tmp_path / "runs"
    # Two agent versions on the same comparability key -> regression trend.
    build_run(base, make_manifest("r-v1", agent_version="agent-1"),
              [_real_work(10)], {"total": 0.6, "checkpoints": {"triage": 0.6}})
    build_run(base, make_manifest("r-v2", agent_version="agent-2"),
              [_real_work(10), _real_work(20)], {"total": 0.9, "checkpoints": {"triage": 0.9}})
    # A different dataset_version but same comparability key — must not split the group.
    build_run(base, make_manifest("r-v3", agent_version="agent-3", dataset_version="ds-999"),
              [_real_work(10)], {"total": 0.4, "checkpoints": {"triage": 0.2, "comms": 0.9}})
    # Reward-hack: lots of messages, no real deltas, low score.
    build_run(base, make_manifest("r-hack", instance_hash="inst-other"),
              [_message(t) for t in range(5)], {"total": 0.1, "checkpoints": {"comms": 0.1}})
    return base


def _index(tmp_path: Path, runs: Path) -> TrajectoryIndex:
    idx = TrajectoryIndex(tmp_path / "index.duckdb")
    idx.rebuild(runs)
    return idx


def test_rows_derived(seeded_runs: Path, tmp_path: Path) -> None:
    idx = _index(tmp_path, seeded_runs)
    rows = {r["run_id"]: r for r in idx.sql("SELECT * FROM runs")}
    assert rows["r-v2"]["n_real_deltas"] == 2
    assert rows["r-hack"]["n_messages"] == 5 and rows["r-hack"]["n_real_deltas"] == 0
    idx.close()


def test_regression_groups_by_comparability_key(seeded_runs: Path, tmp_path: Path) -> None:
    idx = _index(tmp_path, seeded_runs)
    rows = idx.regression("inst-abc")  # dataset edit on r-v3 must NOT drop it from the group
    versions = {r["agent_version"]: r["total"] for r in rows}
    assert versions == {"agent-1": 0.6, "agent-2": 0.9, "agent-3": 0.4}
    assert all(r["action_space_version"] == "v1" for r in rows)
    idx.close()


def test_failure_clusters_by_dropped_checkpoint(seeded_runs: Path, tmp_path: Path) -> None:
    idx = _index(tmp_path, seeded_runs)
    clusters = idx.failure_clusters(threshold=0.5)
    assert clusters["triage"] == ["r-v3"]  # lowest checkpoint for the failing run
    assert clusters["comms"] == ["r-hack"]
    idx.close()


def test_reward_hack_flags_activity_without_outcomes(seeded_runs: Path, tmp_path: Path) -> None:
    idx = _index(tmp_path, seeded_runs)
    flagged = idx.reward_hack()
    assert [r["run_id"] for r in flagged] == ["r-hack"]
    idx.close()


def test_index_is_fully_rebuildable(seeded_runs: Path, tmp_path: Path) -> None:
    idx = _index(tmp_path, seeded_runs)
    before = idx.sql("SELECT * FROM runs ORDER BY run_id")
    idx.rebuild(seeded_runs)  # drop + rebuild
    after = idx.sql("SELECT * FROM runs ORDER BY run_id")
    assert before == after
    idx.close()


def test_refresh_upserts_single_run(seeded_runs: Path, tmp_path: Path) -> None:
    idx = _index(tmp_path, seeded_runs)
    idx.refresh("r-v1", seeded_runs)  # idempotent single-run upsert
    assert len(idx.sql("SELECT run_id FROM runs WHERE run_id = 'r-v1'")) == 1
    idx.close()


def test_sql_rejects_non_select(seeded_runs: Path, tmp_path: Path) -> None:
    idx = _index(tmp_path, seeded_runs)
    with pytest.raises(ValueError):
        idx.sql("DELETE FROM runs")
    idx.close()
