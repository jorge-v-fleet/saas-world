"""End-to-end proof that the `release-triage` archetype ships as pure data.

The engine is archetype-agnostic: this whole scenario (portfolio + validation-gated feature + a
mid-week regression to triage) is authored as a template, with no per-archetype engine code. These
tests exercise it through the real Seeding Engine + loader: the validity gate passes, the reference
solvers separate cleanly (competent full, lazy zero), and the graded fields are un-gameable — an
agent-sourced write to a completion field is refused by the constrained-write guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from saasworld.engine import freeze, generate
from saasworld.engine.gate import gate_once, run_pipeline
from saasworld.engine.solvers import competent_pm, lazy
from saasworld.engine.substrate import load_substrate, load_template
from saasworld.kernel import Kernel
from saasworld.scenario.loader import load as load_scenario
from saasworld.state.store import WorldState

pytestmark = pytest.mark.integration

ARCHETYPE = "release-triage"


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


def test_graded_fields_are_ungameable(tmp_path: Path) -> None:
    # Freeze a real instance and load it, so the loader injects this archetype's denied paths.
    generate(ARCHETYPE, _seed(), out_dir=tmp_path)
    freeze(tmp_path)
    kernel = Kernel(WorldState())
    load_scenario(tmp_path, kernel)

    # A validation-completion field can be written by the system (the gated event) ...
    kernel.state.apply(
        [{"op": "set", "path": "tasks.f1.validated", "value": True}], source="system"
    )
    # ... but never by the agent — so busywork can't fake coverage or the bug fix.
    denied = (
        "tasks.f2.validated",
        "blockers.regression.resolved",
        "projects.billing_v2.true_status",
    )
    for path in denied:
        with pytest.raises(PermissionError):
            kernel.state.apply([{"op": "set", "path": path, "value": True}], source="agent")
