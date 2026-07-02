"""Weighted scoring: project state per checkpoint, grade predicates, append score records.

`score(trajectory, ground_truth)` is a pure function of its inputs: read-only over the trajectory,
appending only its own `checkpoint_score`/`final_score` records (seq above everything read, so
predicates never read a score record — no cycle). Re-scoring the same trajectory is byte-identical.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .predicates import decision_comms, eval_assert
from .project import _get, project
from .rubric import BoundPredicate, Rubric


@dataclass
class PredicateResult:
    id: str
    weight: float
    credit: float
    weighted: float
    status: str  # pass | fail | pending
    reason: str
    reads_real_field: bool


@dataclass
class CheckpointScore:
    checkpoint_id: str
    at: int
    predicates: list[PredicateResult]
    subtotal: float


@dataclass
class WeightedResult:
    scenario_id: str
    checkpoints: list[CheckpointScore]
    artifact_results: list[PredicateResult]
    final: float
    weights_sum: float


def _to_minutes(at: Any) -> int:
    """Accept a sim-minutes int or a 'D<day>T<HH:MM>' offset (parsed by the scenario loader)."""
    if isinstance(at, int):
        return at
    from saasworld.scenario.loader import offset_to_minutes

    return offset_to_minutes(str(at))


def _grade(pred: BoundPredicate, state: Any, baseline: Any) -> PredicateResult:
    if pred.kind == "decision_comms":
        credit, reason, status = decision_comms(pred.spec, state=state, baseline=baseline)
    else:
        credit, reason = eval_assert(pred.spec, state=state, baseline=baseline)
        status = "pass" if credit > 0 else "fail"
    return PredicateResult(
        pred.id, pred.weight, credit, pred.weight * credit, status, reason, pred.reads_real_field
    )


def _next_seq(events: list[Any]) -> int:
    return max((_get(e, "seq") for e in events), default=0) + 1


def score(trajectory: dict[str, Any], ground_truth: dict[str, Any]) -> WeightedResult:
    """Grade the trajectory vs. ground truth; append score records; return the WeightedResult."""
    rubric = Rubric.load(ground_truth)
    t0 = min((s["sim_time"] for s in trajectory.get("snapshots", [])), default=0)
    baseline = project(trajectory, t0)

    checkpoints: list[CheckpointScore] = []
    for cp in rubric.checkpoints:
        at = _to_minutes(cp.at)
        state = project(trajectory, at)
        results = [_grade(p, state, baseline) for p in cp.predicates]
        checkpoints.append(
            CheckpointScore(cp.id, at, results, sum(r.weighted for r in results))
        )

    final_at = max((_to_minutes(cp.at) for cp in rubric.checkpoints), default=t0)
    final_state = project(trajectory, final_at)
    artifacts = [_grade(p, final_state, baseline) for p in rubric.artifacts]

    final = sum(cp.subtotal for cp in checkpoints) + sum(r.weighted for r in artifacts)
    weights_sum = (
        sum(r.weight for cp in checkpoints for r in cp.predicates)
        + sum(r.weight for r in artifacts)
    )
    result = WeightedResult(rubric.scenario_id, checkpoints, artifacts, final, weights_sum)

    _append_records(trajectory, checkpoints, result, final_at)
    return result


def _append_records(
    trajectory: dict[str, Any],
    checkpoints: list[CheckpointScore],
    result: WeightedResult,
    final_at: int,
) -> None:
    """Append checkpoint_score + final_score events, each with a fresh seq above everything read."""
    events = trajectory.setdefault("events", [])
    seq = _next_seq(events)
    for cp in checkpoints:
        events.append(_record(seq, cp.at, "checkpoint_score", asdict(cp)))
        seq += 1
    events.append(_record(seq, final_at, "final_score", asdict(result)))


def _record(seq: int, sim_time: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": seq,
        "sim_time": sim_time,
        "actor": "evaluator",
        "kind": kind,
        "payload": payload,
        "caused_by": None,
    }
