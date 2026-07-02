"""Validation: checkout eval.json binds known kinds, resolves partitions, weights sum to 1.0."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saasworld.eval.rubric import Rubric
from saasworld.state.schema import CORE_PARTITIONS

pytestmark = pytest.mark.validation

EVAL = (Path(__file__).resolve().parents[2]
        / "data" / "scenarios" / "checkout-not-ready" / "eval.json")


def _paths(assertion: dict) -> list[str]:
    """Every state path an assert reads, recursing into `any`."""
    out: list[str] = []
    if "any" in assertion:
        for sub in assertion["any"]:
            out += _paths(sub)
    if "in" in assertion:
        out.append(assertion["in"]["path"])
    if "exists" in assertion:
        out.append(assertion["exists"])
    if "path" in assertion:
        out.append(assertion["path"])
    return out


def _root(path: str) -> str:
    return path.split(".", 1)[0].split("[", 1)[0]


@pytest.fixture
def gt() -> dict:
    return json.loads(EVAL.read_text())


def test_rubric_loads_and_weights_sum_to_one(gt: dict) -> None:
    rubric = Rubric.load(gt)  # raises unless weights sum to 1.0 and every kind is known
    assert rubric.scenario_id == "checkout-not-ready"


def test_every_assert_path_resolves_to_a_real_partition(gt: dict) -> None:
    for cp in gt["checkpoints"]:
        for pred in cp["predicates"]:
            for path in _paths(pred["assert"]):
                assert _root(path) in CORE_PARTITIONS, path


def test_decision_comms_subweights_sum_to_one(gt: dict) -> None:
    for pred in gt["artifact_predicates"]:
        sub = pred["score"]
        total = sum(v["w"] for k, v in sub.items() if isinstance(v, dict) and "w" in v)
        assert total == pytest.approx(1.0)
