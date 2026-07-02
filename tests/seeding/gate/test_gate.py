"""Validity gate: coherence rejects malformed instances; solver gates + resample + verdict cache."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from saasworld.engine.assemble import FactMap
from saasworld.engine.gate import (
    NoValidSeed,
    Reject,
    evaluate,
    find_valid_seed,
    gate_once,
)
from saasworld.engine.substrate import Substrate

pytestmark = pytest.mark.seeding

_PASS = 1.0
_ZERO = 0.0


def _full(_fm: FactMap, _ev: dict[str, Any]) -> float:
    return _PASS


def _none(_fm: FactMap, _ev: dict[str, Any]) -> float:
    return _ZERO


def test_coherence_rejects_two_critical_blockers(
    pipeline: Any, substrate: Substrate, golden_seed: int
) -> None:
    fm, ev = pipeline(golden_seed)
    fm.seed["blockers"].append(dict(fm.seed["blockers"][0], id="blocker.dup"))
    verdict = evaluate(fm, ev, substrate, _full, _none)
    assert not verdict.passed and not verdict.coherence
    assert "critical blocker" in verdict.reason


def test_coherence_rejects_non_active_holder(
    pipeline: Any, substrate: Substrate, golden_seed: int
) -> None:
    fm, ev = pipeline(golden_seed)
    fm.seed["blockers"][0]["known_to"] = ["org.ceo"]  # reference-tier, not bindable
    verdict = evaluate(fm, ev, substrate, _full, _none)
    assert not verdict.coherence and "active-tier" in verdict.reason


def test_coherence_rejects_bad_weights(
    pipeline: Any, substrate: Substrate, golden_seed: int
) -> None:
    fm, ev = pipeline(golden_seed)
    ev["checkpoints"][0]["predicates"][0]["w"] = 0.99
    verdict = evaluate(fm, ev, substrate, _full, _none)
    assert not verdict.coherence and "weights" in verdict.reason


def test_solvable_floor_requires_full_score(
    pipeline: Any, substrate: Substrate, golden_seed: int
) -> None:
    fm, ev = pipeline(golden_seed)
    verdict = evaluate(fm, ev, substrate, lambda *_: 0.6, _none)
    assert verdict.coherence and not verdict.solvable_floor and not verdict.passed


def test_nontrivial_ceiling_requires_lazy_zero(
    pipeline: Any, substrate: Substrate, golden_seed: int
) -> None:
    fm, ev = pipeline(golden_seed)
    verdict = evaluate(fm, ev, substrate, _full, lambda *_: 0.4)
    assert verdict.solvable_floor and not verdict.nontrivial_ceiling


def test_real_solvers_pass_the_golden_seed(
    pipeline: Any, substrate: Substrate, golden_seed: int, template: dict[str, Any]
) -> None:
    verdict, _fm, _ev = gate_once(template, golden_seed, substrate)
    assert verdict.passed


def test_verdict_is_cached_and_skips_the_solvers(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    calls = {"n": 0}

    def counting(_fm: FactMap, _ev: dict[str, Any]) -> float:
        calls["n"] += 1
        return _PASS

    gate_once(template, golden_seed, substrate, counting, _none)
    gate_once(template, golden_seed, substrate, counting, _none)
    assert calls["n"] == 1  # second call hit the verdict cache


def test_reject_resamples_and_logs(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    seen = {"n": 0}

    def fails_first(_fm: FactMap, _ev: dict[str, Any]) -> float:
        seen["n"] += 1
        return _ZERO if seen["n"] == 1 else _PASS

    log: list[Reject] = []
    valid, _fm, _ev, verdict = find_valid_seed(
        template, substrate, golden_seed, budget=4, log=log, competent=fails_first, lazy=_none
    )
    assert verdict.passed and valid == golden_seed + 1  # advanced past the reject
    assert len(log) == 1
    assert log[0].stage == "solvable_floor" and log[0].next_seed == golden_seed + 1


def test_exhausted_budget_raises(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    with pytest.raises(NoValidSeed):
        find_valid_seed(template, substrate, golden_seed, budget=3,
                        competent=_none, lazy=_none)


def test_agent_write_path_invariant_holds(
    pipeline: Any, substrate: Substrate, golden_seed: int
) -> None:
    # Removing the surfaced deny-rule flips coherence — proving the check is live, not decorative.
    from saasworld.engine import gate as gate_mod

    fm, ev = pipeline(golden_seed)
    original = gate_mod.DENIED_PATHS
    gate_mod.DENIED_PATHS = tuple(p for p in original if p != "blockers.*.surfaced")
    try:
        verdict = evaluate(fm, ev, substrate, _full, _none)
    finally:
        gate_mod.DENIED_PATHS = original
    assert not verdict.coherence and "agent write path" in verdict.reason


def test_deepcopy_isolation(pipeline: Any, golden_seed: int) -> None:
    # Two pipeline runs must not share mutable state.
    fm_a, _ = pipeline(golden_seed)
    fm_b, _ = pipeline(golden_seed)
    fm_a.seed["blockers"].append({"id": "x"})
    assert len(fm_b.seed["blockers"]) == 1
    _ = copy.deepcopy(fm_a)
