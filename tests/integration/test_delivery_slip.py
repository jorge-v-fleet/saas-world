"""End-to-end proof that the `delivery-slip` archetype ships as pure data.

The engine is archetype-agnostic: this whole scenario (portfolio + a critical-path functionality
that slips behind a competing work item) is authored as a template, with no per-archetype engine
code. These tests exercise it through the real Seeding Engine + loader: the validity gate passes,
reference solvers separate cleanly (competent full, lazy zero), and the graded fields are
un-gameable — an agent-sourced write to a completion / reprioritization / true_status field is
refused by the constrained-write guard, while the system (the gated effect) may write it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from saasworld.engine import freeze, generate
from saasworld.engine.gate import clear_cache, gate_once, run_pipeline
from saasworld.engine.solvers import competent_pm, lazy
from saasworld.engine.substrate import load_substrate, load_template
from saasworld.kernel import Kernel
from saasworld.scenario.loader import load as load_scenario
from saasworld.state.store import WorldState

pytestmark = pytest.mark.integration

ARCHETYPE = "delivery-slip"


def _seed() -> int:
    return int(load_template(ARCHETYPE)["example_binding"]["_seed"])


def test_validity_gate_passes() -> None:
    # Coherence + solvable-floor (competent >= 1.0) + non-trivial-ceiling (lazy ~0) all hold.
    verdict, _fm, _ev = gate_once(load_template(ARCHETYPE), _seed(), load_substrate())
    assert verdict.passed
    assert verdict.coherence and verdict.solvable_floor and verdict.nontrivial_ceiling


def test_reference_solvers_separate() -> None:
    fm, ev = run_pipeline(load_template(ARCHETYPE), _seed(), load_substrate())
    assert competent_pm(fm, ev) == pytest.approx(1.0)  # real work -> full credit
    assert lazy(fm, ev) == pytest.approx(0.0)           # chatter -> nothing graded moves


def test_coherence_rejects_a_mis_bound_seed() -> None:
    # The binder ignores the `owned_by agent` selector and picks a project by RNG, so some seeds
    # bind critical_project to `platform`. A coherence invariant pins the critical-path task to
    # feature_x, so those seeds fail the gate (and find_valid_seed resamples past them) — every
    # generated instance is valid by construction, not just the pinned example seed.
    tpl, sub = load_template(ARCHETYPE), load_substrate()
    mis_bound = None
    for seed in range(40):
        clear_cache()
        fm, _ = run_pipeline(tpl, seed, sub)
        if fm.ids.get("critical_project") != "feature_x":
            mis_bound = seed
            break
    assert mis_bound is not None, "expected at least one mis-binding seed in 0..39"
    clear_cache()
    verdict, _fm, _ev = gate_once(tpl, mis_bound, sub)
    assert not verdict.passed and not verdict.coherence


def test_graded_fields_are_ungameable(tmp_path: Path) -> None:
    # Freeze a real instance and load it, so the loader injects this archetype's denied paths.
    generate(ARCHETYPE, _seed(), out_dir=tmp_path)
    freeze(tmp_path)
    kernel = Kernel(WorldState())
    load_scenario(tmp_path, kernel)

    # A completion field can be written by the system (the gated event) ...
    kernel.state.apply(
        [{"op": "set", "path": "tasks.f2.done", "value": True}], source="system"
    )
    # ... but never by the agent — so busywork can't fake recovery, reprioritization, or the truth.
    denied = (
        "tasks.f2.done",
        "tasks.w1.deprioritized",
        "projects.feature_x.true_status",
    )
    for path in denied:
        with pytest.raises(PermissionError):
            kernel.state.apply([{"op": "set", "path": path, "value": True}], source="agent")
