"""Validity gate: coherence (pure) -> solvable-floor -> non-trivial-ceiling, cached by the key.

Coherence is a pure invariant check; the two score gates drive rule-scripted reference solvers and
read only their deterministic final score. A reject is logged and the search advances to the next
seed (bounded -> `NoValidSeed`), so coverage is never silently dropped. The verdict is memoized by
`(template_id, seed, substrate_hash, generator_version)` — a second call skips the solvers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..eval import paths as _paths
from ..state.guard import DENIED_PATHS
from ..state.store import WorldState
from . import solvers as _solvers
from .assemble import FactMap, assemble
from .bind import bind
from .project import project_eval
from .sample import sample
from .substrate import Substrate
from .types import GENERATOR_VERSION, Verdict

_SCORE_EPS = 1e-9

Key = tuple[str, int, str, str]
Solver = Callable[[FactMap, dict[str, Any]], float]

_VERDICT_CACHE: dict[Key, Verdict] = {}


class NoValidSeed(RuntimeError):
    """The resample budget was exhausted without a passing seed."""


@dataclass
class Reject:
    key: Key
    stage: str
    reason: str
    next_seed: int


def clear_cache() -> None:
    _VERDICT_CACHE.clear()


def make_key(template: dict[str, Any], seed: int, substrate: Substrate) -> Key:
    return (template["archetype"], seed, substrate.hash, GENERATOR_VERSION)


def run_pipeline(
    template: dict[str, Any], seed: int, substrate: Substrate
) -> tuple[FactMap, dict[str, Any]]:
    """The pure generate path: sample -> bind -> assemble -> project_eval."""
    draw = sample(template, seed, substrate.hash)
    binding = bind(template, draw, substrate, seed)
    factmap = assemble(template, draw, binding, substrate)
    return factmap, project_eval(factmap, template)


def check_coherence(
    factmap: FactMap, eval_json: dict[str, Any], substrate: Substrate
) -> tuple[bool, str]:
    """Interpret the template's declarative invariants; first failure returns its `reason`."""
    view = WorldState(dict(factmap.seed))
    for inv in factmap.coherence:
        if not _invariant_ok(inv, view, factmap, eval_json, substrate):
            return False, str(inv["reason"])
    return True, "ok"


def _one(node: Any) -> Any:
    """The single matched item of a filter read (first of a list), or the scalar itself."""
    if isinstance(node, list):
        return node[0] if node else None
    return node


def _active(substrate: Substrate, pid: str) -> bool:
    person = substrate.people.get(pid)
    return person is not None and person.tier == "active"


def _invariant_ok(
    inv: dict[str, Any], view: WorldState, factmap: FactMap,
    eval_json: dict[str, Any], substrate: Substrate,
) -> bool:
    """Evaluate one invariant against seed (via `view`) / overlay / eval / substrate / denied."""
    if "count" in inv:
        got = _paths.read(view, inv["count"])
        return bool((len(got) if isinstance(got, list) else 0) == inv["eq"])
    if "count_field" in inv:
        spec = inv["count_field"]
        item = _one(_paths.read(view, spec["path"]))
        val = item.get(spec["field"], []) if isinstance(item, dict) else []
        return bool(len(val) == inv["eq"])
    if "field_eq" in inv:
        spec = inv["field_eq"]
        item = _one(_paths.read(view, spec["path"]))
        return isinstance(item, dict) and item.get(spec["field"]) == inv["eq"]
    if "holder_tier_active" in inv:
        spec = inv["holder_tier_active"]
        item = _one(_paths.read(view, spec["path"]))
        ids = item.get(spec["field"], []) if isinstance(item, dict) else []
        return bool(ids) and all(_active(substrate, pid) for pid in ids)
    if "reveal_path_exists" in inv:
        item = _one(_paths.read(view, inv["reveal_path_exists"]["blocker_path"]))
        bid = item.get("id") if isinstance(item, dict) else None
        return any(
            k.get("links_blocker") == bid and k.get("reveal_when")
            for ov in factmap.overlay.values() for k in ov.get("knowledge_scope", [])
        )
    if "denied_path" in inv:
        return inv["denied_path"] in DENIED_PATHS  # module-level: honors a test monkeypatch
    if "weights_sum" in inv:
        return bool(abs(_weights(eval_json) - inv["weights_sum"]) <= _SCORE_EPS)
    return False


def _weights(eval_json: dict[str, Any]) -> float:
    total = sum(float(p["w"]) for cp in eval_json.get("checkpoints", [])
                for p in cp.get("predicates", []))
    total += sum(float(p["w"]) for p in eval_json.get("artifact_predicates", []))
    return total


def evaluate(
    factmap: FactMap, eval_json: dict[str, Any], substrate: Substrate,
    competent: Solver, lazy: Solver,
) -> Verdict:
    """Score the three gates for an already-assembled instance (no cache, no resample)."""
    ok, reason = check_coherence(factmap, eval_json, substrate)
    if not ok:
        return Verdict(False, False, False, False, reason)
    floor = competent(factmap, eval_json) >= 1.0 - _SCORE_EPS
    if not floor:
        return Verdict(False, True, False, False, "competent-PM solver did not reach full score")
    ceiling = lazy(factmap, eval_json) <= _SCORE_EPS
    if not ceiling:
        return Verdict(False, True, True, False, "lazy solver scored above the trivial floor")
    return Verdict(True, True, True, True, "ok")


def gate_once(
    template: dict[str, Any], seed: int, substrate: Substrate,
    competent: Solver | None = None, lazy: Solver | None = None,
) -> tuple[Verdict, FactMap, dict[str, Any]]:
    """Gate a single seed; the verdict is memoized so a repeat call skips the solvers."""
    factmap, eval_json = run_pipeline(template, seed, substrate)
    key = make_key(template, seed, substrate)
    cached = _VERDICT_CACHE.get(key)
    if cached is not None:
        return cached, factmap, eval_json
    verdict = evaluate(
        factmap, eval_json, substrate,
        competent or _solvers.competent_pm, lazy or _solvers.lazy,
    )
    _VERDICT_CACHE[key] = verdict
    return verdict, factmap, eval_json


def _stage(verdict: Verdict) -> str:
    if not verdict.coherence:
        return "coherence"
    if not verdict.solvable_floor:
        return "solvable_floor"
    return "nontrivial_ceiling"


def find_valid_seed(
    template: dict[str, Any], substrate: Substrate, seed: int, budget: int = 32,
    log: list[Reject] | None = None,
    competent: Solver | None = None, lazy: Solver | None = None,
) -> tuple[int, FactMap, dict[str, Any], Verdict]:
    """Resample from `seed` until a valid instance; log every reject; bounded -> NoValidSeed."""
    current = seed
    for _ in range(budget):
        verdict, factmap, eval_json = gate_once(template, current, substrate, competent, lazy)
        if verdict.passed:
            return current, factmap, eval_json, verdict
        nxt = current + 1
        if log is not None:
            log.append(Reject(make_key(template, current, substrate), _stage(verdict),
                              verdict.reason, nxt))
        current = nxt
    raise NoValidSeed(f"no valid seed within {budget} of {seed}")
