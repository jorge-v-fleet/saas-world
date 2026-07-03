"""Seeding Engine — templates + seeds -> frozen instances (co-generated eval, validity gate).

Build-time only: deterministic, offline, and never run during a graded episode. A template + a seed
resolve to one immutable instance whose world and `eval.json` project from the *same* fact-map, so
grader and world can't drift. The three functions below are the public surface the operator CLI
drives; the pipeline stages (sample -> bind -> assemble -> project_eval -> gate -> freeze) live in
sibling modules. The dataclass fields and function signatures here are a stable contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import freeze as _freeze
from .gate import evaluate, run_pipeline
from .substrate import load_substrate, load_template
from .types import FreezeResult, GenerateResult, Verdict

_DEFAULT_OUT = Path(__file__).resolve().parents[3] / "data" / "candidates"


def generate(archetype: str, seed: int, out_dir: str | Path | None = None) -> GenerateResult:
    """Run sample -> bind -> assemble -> project_eval and write a candidate (unfrozen) instance."""
    substrate = load_substrate()
    template = load_template(archetype)
    factmap, eval_json = run_pipeline(template, seed, substrate)
    out = Path(out_dir) if out_dir is not None else _DEFAULT_OUT / f"{archetype}-{seed}"
    _freeze.write_candidate(
        out, archetype, seed, factmap, eval_json, substrate.hash, template.get("denied_paths"),
    )
    # Archetype-agnostic summary: bound ids plus any well-known bindings the template happens to
    # carry (absent keys are simply omitted, so a new archetype never KeyErrors here).
    b = factmap.bindings
    summary = {
        k: v for k, v in {
            "blocker": b.get("blocker"),
            "holder": factmap.ids.get("blocker.holder") or factmap.ids.get("holder"),
            "critical_project": factmap.ids.get("critical_project"),
            "stakeholder": factmap.ids.get("stakeholder"),
            "movable": b.get("movable"),
        }.items() if v is not None
    }
    return GenerateResult(out, archetype, seed, factmap.activate, summary)


def validate(instance_dir: str | Path) -> Verdict:
    """Run the validity gate (coherence, solvable-floor, non-trivial-ceiling) over an instance."""
    root = Path(instance_dir)
    manifest = json.loads((root / "scenario.json").read_text())
    prov = manifest["provenance"]
    substrate = load_substrate()
    template = load_template(prov["template_id"])
    factmap, eval_json = run_pipeline(template, int(prov["seed"]), substrate)
    from .solvers import competent_pm, lazy

    return evaluate(factmap, eval_json, substrate, competent_pm, lazy)


def freeze(instance_dir: str | Path) -> FreezeResult:
    """Content-hash + provenance-stamp an instance, mark it immutable (writes `scenario.json`)."""
    return _freeze.freeze(instance_dir)


__all__ = ["FreezeResult", "GenerateResult", "Verdict", "freeze", "generate", "validate"]
