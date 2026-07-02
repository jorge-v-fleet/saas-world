"""Scoring: real work ~1.0, activity-only ~0.0, exact partial credit, append-only score records."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from saasworld.eval.score import score

pytestmark = pytest.mark.evaluator

_EVAL = (Path(__file__).resolve().parents[2]
         / "data" / "scenarios" / "checkout-not-ready" / "eval.json")


@pytest.fixture
def eval_gt() -> dict:
    return json.loads(_EVAL.read_text())


def test_real_work_scores_one(realwork_trajectory: dict, eval_gt: dict) -> None:
    result = score(realwork_trajectory, eval_gt)
    assert result.final == pytest.approx(1.0)
    assert result.weights_sum == pytest.approx(1.0)
    per = {r.id: (r.status, r.credit) for cp in result.checkpoints for r in cp.predicates}
    assert per["blocker_surfaced"] == ("pass", 1.0)
    assert per["correct_action"] == ("pass", 1.0)
    assert result.artifact_results[0].status == "pass"


def test_activity_only_scores_zero(activity_trajectory: dict, eval_gt: dict) -> None:
    result = score(activity_trajectory, eval_gt)
    assert result.final == pytest.approx(0.0)
    assert all(r.credit == 0.0 for cp in result.checkpoints for r in cp.predicates)
    assert result.artifact_results[0].status == "pending"


def test_exact_partial_credit(realwork_trajectory: dict, eval_gt: dict) -> None:
    # drop only the CTO message -> lose stakeholder_informed (0.10); everything else stands.
    traj = copy.deepcopy(realwork_trajectory)
    traj["events"] = [e for e in traj["events"] if e["seq"] != 4]
    result = score(traj, eval_gt)
    assert result.final == pytest.approx(0.90)
    per = {r.id: r.status for cp in result.checkpoints for r in cp.predicates}
    assert per["stakeholder_informed"] == "fail"


def test_append_only_records_and_no_cycle(realwork_trajectory: dict, eval_gt: dict) -> None:
    before_max = max(e["seq"] for e in realwork_trajectory["events"])
    result = score(realwork_trajectory, eval_gt)
    appended = [e for e in realwork_trajectory["events"] if e["actor"] == "evaluator"]
    kinds = [e["kind"] for e in appended]
    assert kinds == ["checkpoint_score", "final_score"]
    assert all(e["seq"] > before_max for e in appended)  # above everything read
    # Re-scoring the trajectory that now carries score records yields the identical result:
    # predicates never read a score record (score events carry no deltas -> no cycle).
    again = score(realwork_trajectory, eval_gt)
    assert asdict(again) == asdict(result)
