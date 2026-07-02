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

from ..state.guard import DENIED_PATHS
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
    seed_json: dict[str, Any], overlay: dict[str, Any], eval_json: dict[str, Any],
    substrate: Substrate,
) -> tuple[bool, str]:
    """Pure invariants: one critical blocker, active holder, a reveal path, no write, weights."""
    critical = [b for b in seed_json.get("blockers", []) if b.get("severity") == "launch_blocking"]
    if len(critical) != 1:
        return False, f"expected exactly one critical blocker, found {len(critical)}"
    blk = critical[0]
    known = blk.get("known_to", [])
    if len(known) != 1:
        return False, "critical blocker must be known_to exactly one NPC at seed"
    person = substrate.people.get(known[0])
    if person is None or person.tier != "active":
        return False, f"holder {known[0]!r} is not an active-tier NPC"
    if blk.get("surfaced") is not False:
        return False, "critical blocker must start surfaced=false"
    reveal = any(
        item.get("links_blocker") == blk["id"] and item.get("reveal_when")
        for ov in overlay.values() for item in ov.get("knowledge_scope", [])
    )
    if not reveal:
        return False, "no NPC reveal path can flip surfaced"
    if "blockers.*.surfaced" not in DENIED_PATHS:
        return False, "surfaced has an agent write path"
    total = _weights(eval_json)
    if abs(total - 1.0) > _SCORE_EPS:
        return False, f"eval weights sum to {total}, expected 1.0"
    return True, "ok"


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
    ok, reason = check_coherence(factmap.seed, factmap.overlay, eval_json, substrate)
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
