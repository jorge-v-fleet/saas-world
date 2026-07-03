"""deal-escalation template: gate passes, un-gameable discovery, winnable-AND-losable commit.

The competent reference PM asks Eng (the reveal surfaces feasibility, system-sourced), records the
feasibility-grounded commit/decline, and informs Sales/CS/stakeholder -> full score. The lazy PM
promises the date and chatters, never asking Eng -> ~0. The three system-only fields are denied to
the agent, so discovery and correctness can't be faked.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from saasworld.engine import solvers as S
from saasworld.engine.gate import clear_cache, gate_once, run_pipeline
from saasworld.engine.substrate import load_substrate, load_template
from saasworld.state.store import WorldState

pytestmark = pytest.mark.seeding

_EPS = 1e-9
# scanned green below; seed 1 is infeasible, 2-4 feasible (both outcomes covered)
_GOOD_SEEDS = (1, 2, 3, 4)


@pytest.fixture(autouse=True)
def _reset_cache() -> Any:
    clear_cache()
    yield
    clear_cache()


def _tpl() -> dict[str, Any]:
    return load_template("deal-escalation")


def test_gate_passes_for_multiple_seeds() -> None:
    sub, tpl = load_substrate(), _tpl()
    for seed in _GOOD_SEEDS:
        verdict, _, _ = gate_once(tpl, seed, sub)
        assert verdict.passed, (seed, verdict.reason)


def test_weights_sum_to_one() -> None:
    sub, tpl = load_substrate(), _tpl()
    _, ev = run_pipeline(tpl, 1, sub)
    w = sum(p["w"] for cp in ev["checkpoints"] for p in cp["predicates"])
    w += sum(p["w"] for p in ev.get("artifact_predicates", []))
    assert abs(w - 1.0) <= _EPS


def test_competent_full_lazy_zero_both_outcomes() -> None:
    sub, tpl = load_substrate(), _tpl()
    seen_feasible: set[bool] = set()
    for seed in _GOOD_SEEDS:
        fm, ev = run_pipeline(tpl, seed, sub)
        seen_feasible.add(bool(fm.draw["deal.feasible_by_date"]))
        assert S.competent_pm(fm, ev) >= 1.0 - _EPS, seed
        assert S.lazy(fm, ev) <= _EPS, seed
    assert seen_feasible == {True, False}  # winnable AND losable across the family


def test_correct_set_tracks_feasibility() -> None:
    sub, tpl = load_substrate(), _tpl()
    for seed in _GOOD_SEEDS:
        fm, _ = run_pipeline(tpl, seed, sub)
        want = ["commit"] if fm.draw["deal.feasible_by_date"] else ["decline", "counter_offer"]
        assert fm.bindings["correct_set"] == want, seed


def test_system_only_fields_denied_to_agent() -> None:
    sub, tpl = load_substrate(), _tpl()
    fm, _ = run_pipeline(tpl, 1, sub)
    world = WorldState()
    world.restore(S._seed_world(fm.seed))
    world.set_denied_paths(tpl["denied_paths"])
    assert "projects.deal.feasibility_surfaced" in tpl["denied_paths"]
    for path in tpl["denied_paths"]:
        with pytest.raises(PermissionError):
            world.apply([{"op": "set", "path": path, "value": True}], source="agent")
    # system is the only writer that may flip them
    flip = [{"op": "set", "path": "projects.deal.feasibility_surfaced", "value": True}]
    world.apply(flip, source="system")


def test_naive_always_commit_loses_on_infeasible_seed() -> None:
    """An agent that commits without asking Eng forfeits discovery (0.25) + correctness (0.25)."""
    sub, tpl = load_substrate(), _tpl()
    fm, ev = run_pipeline(tpl, 1, sub)  # seed 1 is infeasible
    assert fm.draw["deal.feasible_by_date"] is False
    naive = [
        {"at": 60, "actor": "agent", "verb": "record_decision",
         "args": {"about": "deal", "type": "commit", "action": "commit"}},
        {"at": 70, "actor": "agent", "verb": "send_message",
         "args": {"to": fm.ids["ae"], "body": "x", "refs": ["deal"]}},
        {"at": 80, "actor": "agent", "verb": "send_message",
         "args": {"to": fm.ids["cs"], "body": "x", "refs": ["account_risk"]}},
        {"at": 90, "actor": "agent", "verb": "send_message",
         "args": {"to": fm.ids["stakeholder"], "body": "x", "refs": ["deal"]}},
        {"advance_until": 100},
    ]
    fm2 = copy.copy(fm)
    fm2.solvers = {**fm.solvers, "naive": naive}
    assert abs(S._run_script(fm2, ev, naive) - 0.5) <= _EPS


def test_autonomous_flag_propagates_to_manifest(tmp_path: Any) -> None:
    from saasworld.engine import freeze, generate

    res = generate("deal-escalation", 1, out_dir=tmp_path)
    import json

    manifest = json.loads((tmp_path / "scenario.json").read_text())
    assert manifest["autonomous_npcs"] is True
    assert "deal" in res.summary["critical_project"]
    freeze(tmp_path)  # freezes without error
