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
from typing import Any

from . import freeze as _freeze
from .gate import evaluate, gate_once, run_pipeline
from .substrate import load_substrate, load_template
from .types import GENERATOR_VERSION, BuildSetResult, FreezeResult, GenerateResult, Verdict

_DATA = Path(__file__).resolve().parents[3] / "data"
_DEFAULT_OUT = _DATA / "candidates"
_SCENARIOS = _DATA / "scenarios"
_SETS = _DATA / "sets"


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


def _existing_by_seed(archetype: str, root: Path) -> dict[int, str]:
    """Map seed -> instance dir for already-materialized scenarios of this archetype (any name),
    so a set reuses a hand-authored instance (e.g. checkout-not-ready) instead of duplicating it."""
    out: dict[int, str] = {}
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        manifest = d / "scenario.json"
        if not manifest.is_dir() and manifest.exists():
            prov = json.loads(manifest.read_text()).get("provenance", {})
            if prov.get("template_id") == archetype and "seed" in prov:
                out[int(prov["seed"])] = d.name
    return out


def build_set(
    archetype: str, count: int, start: int = 0, scan_limit: int = 256,
    out_root: str | Path | None = None,
) -> BuildSetResult:
    """Materialize the first `count` VALID instances at or after `start`, skipping seeds the gate
    rejects, and write a manifest recording exactly which seeds back the set. Deterministic: same
    (substrate, template, start) always yields the same seed list. Reuses an existing instance dir
    for a seed already materialized under a curated name, so the set never duplicates it."""
    substrate = load_substrate()
    template = load_template(archetype)
    from .solvers import competent_pm, lazy

    root = Path(out_root) if out_root is not None else _SCENARIOS
    existing = _existing_by_seed(archetype, root)
    denied = template.get("denied_paths")

    members: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seed = start
    while len(members) < count and seed - start < scan_limit:
        verdict, factmap, eval_json = gate_once(template, seed, substrate, competent_pm, lazy)
        if verdict.passed:
            name = existing.get(seed)
            if name is None:
                out = root / f"{archetype}-{seed}"
                _freeze.write_candidate(
                    out, archetype, seed, factmap, eval_json, substrate.hash, denied)
                _freeze.freeze(out)
                name = out.name
            members.append({
                "seed": seed, "dir": name,
                "feature": factmap.draw.get("feature.name"),
                "blocker": factmap.draw.get("blocker.type"),
                "critical_project": factmap.ids.get("critical_project"),
                "holder": factmap.ids.get("holder"),
                "stakeholder": factmap.ids.get("stakeholder"),
            })
        else:
            rejected.append({"seed": seed, "reason": verdict.reason})
        seed += 1

    _SETS.mkdir(parents=True, exist_ok=True)
    manifest_path = _SETS / f"{archetype}.json"
    manifest = {
        "archetype": archetype,
        "generator_version": GENERATOR_VERSION,
        "substrate_hash": substrate.hash,
        "requested_count": count, "start_seed": start, "scan_limit": scan_limit,
        "scanned_through": seed - 1,
        "seeds": [m["seed"] for m in members],
        "members": members,
        "rejected": rejected,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return BuildSetResult(
        archetype=archetype, manifest_path=manifest_path,
        seeds=[m["seed"] for m in members], dirs=[m["dir"] for m in members],
        rejected=len(rejected), scanned_through=seed - 1,
    )


__all__ = [
    "BuildSetResult", "FreezeResult", "GenerateResult", "Verdict",
    "build_set", "freeze", "generate", "validate",
]
