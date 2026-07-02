"""Pure predicate kinds. Each reads a real graded field by path and returns (credit, reason).

Never trusts prose: field equality, set/enum membership, existence, message-match (existence with
refs/references aliasing), changed-since-baseline, any (disjunction), and the state-grounded
``decision_comms``. Missing paths score 0 with a reason, never crash.
"""

from __future__ import annotations

import re
from typing import Any

from .paths import MISSING, read

Result = tuple[float, str]

# Scenario-anchored grounding paths for decision_comms (mirror eval.json requires_state prose).
_BLOCKER_SURFACED = "blockers.blocker.psp_cert.surfaced"


def field_eq(spec: dict[str, Any], *, state: Any, baseline: Any = None) -> Result:
    path, want = spec["path"], spec["eq"]
    got = read(state, path)
    if got is MISSING:
        return 0.0, f"{path} missing"
    return (1.0, f"{path} == {want!r}") if got == want else (0.0, f"{path} is {got!r} != {want!r}")


def set_membership(spec: dict[str, Any], *, state: Any, baseline: Any = None) -> Result:
    inner = spec["in"]
    path, allowed = inner["path"], inner["set"]
    got = read(state, path)
    if got is MISSING:
        return 0.0, f"{path} missing"
    vals = got if isinstance(got, list) else [got]
    return (
        (1.0, f"{path} in {allowed}")
        if any(v in allowed for v in vals)
        else (0.0, f"{path}={vals} not in {allowed}")
    )


def existence(spec: dict[str, Any], *, state: Any, baseline: Any = None) -> Result:
    expr = spec["exists"]
    got = read(state, expr)
    n = len(got) if isinstance(got, list) else 0
    return (1.0, f"{expr} matched {n}") if n else (0.0, f"{expr} matched none")


def changed(spec: dict[str, Any], *, state: Any, baseline: Any) -> Result:
    path = spec["path"]
    cur, base = read(state, path), read(baseline, path)
    return (1.0, f"{path} changed") if cur != base else (0.0, f"{path} unchanged ({cur!r})")


def any_of(spec: dict[str, Any], *, state: Any, baseline: Any = None) -> Result:
    reasons: list[str] = []
    for sub in spec["any"]:
        credit, reason = eval_assert(sub, state=state, baseline=baseline)
        reasons.append(reason)
        if credit >= 1.0:
            return 1.0, f"any: {reason}"
    return 0.0, "any: none (" + "; ".join(reasons) + ")"


def eval_assert(spec: dict[str, Any], *, state: Any, baseline: Any = None) -> Result:
    """Dispatch an assert dict to its predicate kind (also used for `any` sub-asserts)."""
    if "any" in spec:
        return any_of(spec, state=state, baseline=baseline)
    if "in" in spec:
        return set_membership(spec, state=state, baseline=baseline)
    if "exists" in spec:
        return existence(spec, state=state, baseline=baseline)
    if "changed" in spec:
        return changed(spec, state=state, baseline=baseline)
    if "eq" in spec:
        return field_eq(spec, state=state, baseline=baseline)
    return 0.0, f"unknown assert {sorted(spec)}"


def _about(source: str) -> str | None:
    m = re.search(r"about='([^']+)'", source)
    return m.group(1) if m else None


def decision_comms(pred: dict[str, Any], *, state: Any, baseline: Any) -> tuple[float, str, str]:
    """State-grounded artifact grade. Reads the structured record_decision and credits each
    sub-field only if world state backs it; a free-text-only artifact is `pending` (deferred)."""
    about = _about(pred.get("source", "")) or "proj.checkout"
    decisions = read(state, "decisions")
    matches = [d for d in decisions if isinstance(d, dict) and d.get("about") == about] \
        if isinstance(decisions, list) else []
    if not matches:
        return 0.0, "no structured record_decision; free-text deferred to extractor", "pending"

    decision = matches[-1]
    sub = pred["score"]
    credit = 0.0
    parts: list[str] = []

    surfaced = read(state, _BLOCKER_SURFACED) is True
    if surfaced:
        credit += sub["cites_blocker"]["w"]
    parts.append(f"cites_blocker={'ok' if surfaced else '0'}")

    date_path = f"projects.{about}.launch_date"
    date_moved = read(state, date_path) != read(baseline, date_path)
    if decision.get("new_date") is not None and date_moved:
        credit += sub["new_date"]["w"]
        parts.append("new_date=ok")
    else:
        parts.append("new_date=0")

    owner = decision.get("owner")
    org = read(state, "org")
    if owner is not None and isinstance(org, dict) and owner in org:
        credit += sub["owner"]["w"]
        parts.append("owner=ok")
    else:
        parts.append("owner=0")

    return credit, "; ".join(parts), "pass"
