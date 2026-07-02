"""Rubric: binds each predicate to a known kind; loads iff weights sum to 1.0, else refuses."""

from __future__ import annotations

import copy

import pytest

from saasworld.eval.rubric import Rubric

pytestmark = pytest.mark.evaluator

_GT = {
    "_scenario": "t",
    "checkpoints": [{"id": "c", "at": 10, "predicates": [
        {"id": "a", "w": 0.5, "assert": {"path": "x.y", "eq": True}},
        {"id": "b", "w": 0.3, "assert": {"exists": "z[?k=='v']"}},
    ]}],
    "artifact_predicates": [{"id": "d", "w": 0.2,
                             "source": "action:record_decision(about='p')", "score": {}}],
}


def test_valid_weights_load_and_bind_kinds() -> None:
    r = Rubric.load(copy.deepcopy(_GT))
    kinds = {p.id: p.kind for cp in r.checkpoints for p in cp.predicates}
    kinds.update({p.id: p.kind for p in r.artifacts})
    assert kinds == {"a": "eq", "b": "existence", "d": "decision_comms"}


def test_weights_not_summing_to_one_refuses() -> None:
    bad = copy.deepcopy(_GT)
    bad["artifact_predicates"][0]["w"] = 0.5  # total 1.3
    with pytest.raises(ValueError, match="weights sum"):
        Rubric.load(bad)


def test_unknown_assert_kind_refuses() -> None:
    bad = copy.deepcopy(_GT)
    bad["checkpoints"][0]["predicates"][0]["assert"] = {"bogus": 1}
    with pytest.raises(ValueError, match="assert kind"):
        Rubric.load(bad)
