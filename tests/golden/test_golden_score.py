"""Grade == replayable: a fixed committed trajectory scores to a byte-identical breakdown.

Loads the real checkout-not-ready eval.json, scores the frozen trajectory, and asserts the canonical
WeightedResult against a stored golden. Re-scoring is byte-identical. Regenerate with
``pytest --update-golden``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from saasworld.eval.score import score

pytestmark = pytest.mark.golden

_HERE = Path(__file__).parent
TRAJECTORY = _HERE / "score_trajectory.json"
GOLDEN = _HERE / "score_breakdown.json"
EVAL = (_HERE.parents[1] / "data" / "scenarios" / "checkout-not-ready" / "eval.json")


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, indent=2)


def _score() -> dict:
    trajectory = json.loads(TRAJECTORY.read_text())  # fresh copy: score() appends records
    gt = json.loads(EVAL.read_text())
    return asdict(score(trajectory, gt))


def test_score_matches_golden(update_golden: bool) -> None:
    text = _canonical(_score())
    if update_golden:
        GOLDEN.write_text(text + "\n")
        return
    assert text + "\n" == GOLDEN.read_text()


def test_rescoring_is_byte_identical() -> None:
    trajectory = json.loads(TRAJECTORY.read_text())
    gt = json.loads(EVAL.read_text())
    first = _canonical(asdict(score(copy.deepcopy(trajectory), gt)))
    second = _canonical(asdict(score(copy.deepcopy(trajectory), gt)))
    assert first == second
