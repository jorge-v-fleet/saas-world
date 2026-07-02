"""Projection: nearest snapshot <= at, replay in (sim_time, seq) order; baseline == snapshots[0]."""

from __future__ import annotations

import copy

import pytest

from saasworld.eval.project import project

from .conftest import SEED

pytestmark = pytest.mark.evaluator


def test_baseline_equals_seed_snapshot(realwork_trajectory: dict) -> None:
    assert project(realwork_trajectory, 0).snapshot() == SEED


def test_projection_applies_events_up_to_at(realwork_trajectory: dict) -> None:
    # at=105 -> only the reveal (seq1@100) applied, not the reschedule (seq2@110).
    st = project(realwork_trajectory, 105)
    assert st.read("blockers.blocker.psp_cert.surfaced") is True
    assert st.read("projects.proj.checkout.launch_date") == "D5T17:00"


def test_projection_full_horizon(realwork_trajectory: dict) -> None:
    st = project(realwork_trajectory, 10_000)
    assert st.read("projects.proj.checkout.launch_date") == "D8T17:00"
    assert len(st.read("decisions")) == 1


def test_projection_is_read_only(realwork_trajectory: dict) -> None:
    before = copy.deepcopy(realwork_trajectory)
    project(realwork_trajectory, 10_000)
    assert realwork_trajectory == before  # trajectory (incl. seed snapshot) untouched


def test_later_snapshot_is_restored_without_double_apply() -> None:
    # Two snapshots + an append event before the later snapshot must not double-append.
    traj = {
        "snapshots": [
            {"sim_time": 0, "seq": 0, "state": copy.deepcopy(SEED)},
            {"sim_time": 200, "seq": 2, "state": {**copy.deepcopy(SEED),
                                                  "decisions": [{"about": "proj.checkout"}]}},
        ],
        "events": [
            {"seq": 1, "sim_time": 100, "actor": "agent", "kind": "x",
             "payload": {"deltas": [{"op": "append", "path": "decisions",
                                     "value": {"about": "proj.checkout"}}]}, "caused_by": None},
        ],
    }
    st = project(traj, 300)  # restore snap@seq2, replay nothing (event seq1 <= base_seq)
    assert len(st.read("decisions")) == 1
