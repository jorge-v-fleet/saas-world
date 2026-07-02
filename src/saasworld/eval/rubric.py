"""Load eval.json, bind each predicate to a known kind, validate the weights union sums to 1.0."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EPSILON = 1e-9

# assert key -> bound kind name.
_ASSERT_KINDS = {"any": "any", "in": "set", "exists": "existence", "changed": "changed", "eq": "eq"}


@dataclass
class BoundPredicate:
    id: str
    weight: float
    kind: str
    spec: dict[str, Any]  # the `assert` dict, or the full predicate for decision_comms
    reads_real_field: bool


@dataclass
class Checkpoint:
    id: str
    at: Any  # sim-minutes int or a "D<day>T<HH:MM>" offset
    predicates: list[BoundPredicate]


@dataclass
class Rubric:
    scenario_id: str
    checkpoints: list[Checkpoint]
    artifacts: list[BoundPredicate]

    @classmethod
    def load(cls, ground_truth: dict[str, Any] | str | Path) -> Rubric:
        """Parse ground truth (dict or eval.json path), bind kinds, refuse if weights != 1.0."""
        gt = ground_truth
        if isinstance(gt, (str, Path)):
            gt = json.loads(Path(gt).read_text())
        assert isinstance(gt, dict)

        checkpoints = [
            Checkpoint(cp["id"], cp["at"], [_bind(p) for p in cp.get("predicates", [])])
            for cp in gt.get("checkpoints", [])
        ]
        artifacts = [_bind(p) for p in gt.get("artifact_predicates", [])]

        total = sum(p.weight for cp in checkpoints for p in cp.predicates)
        total += sum(p.weight for p in artifacts)
        if abs(total - 1.0) > EPSILON:
            raise ValueError(f"rubric weights sum to {total}, expected 1.0")
        return cls(gt.get("_scenario", "unknown"), checkpoints, artifacts)


def _bind(pred: dict[str, Any]) -> BoundPredicate:
    weight = float(pred["w"])
    reads = bool(pred.get("reads_real_field", True))
    if "source" in pred:
        return BoundPredicate(pred["id"], weight, "decision_comms", pred, reads)
    assertion = pred["assert"]
    kind = next((_ASSERT_KINDS[k] for k in _ASSERT_KINDS if k in assertion), None)
    if kind is None:
        raise ValueError(f"predicate {pred.get('id')!r}: unknown assert kind {sorted(assertion)}")
    return BoundPredicate(pred["id"], weight, kind, assertion, reads)
