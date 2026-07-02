"""POV projection — a pure, on-demand view of the log for one actor at one sim-time.

Never materialized: each call reconstructs ``state_at`` the last event with ``sim_time <= at`` and
filters it (plus the visible events) through the actor's scope. operator/omniscient see the full
log; agent/npc/grader see only their scope. Scopes are supplied by the caller here; real persona
``view_scope`` descriptors plug into the same seam later.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .replay import read_records, state_at

# Actors that bypass scoping and observe the whole canonical log.
OMNISCIENT: frozenset[str] = frozenset({"operator", "omniscient"})

# Scope descriptor per actor: visible dotted path-prefixes + extra actor ids whose events are shown.
Scope = dict[str, list[str]]
Scopes = dict[str, Scope]


@dataclass
class View:
    """One actor's projection: scoped state + the events it could see, plus role extras (grader)."""

    actor: str
    at: int
    seq: int
    state: dict[str, Any]
    events: list[dict[str, Any]]
    extras: dict[str, Any] = field(default_factory=dict)


def _read(state: dict[str, Any], path: str) -> Any:
    node: Any = state
    for seg in path.split("."):
        if not isinstance(node, dict) or seg not in node:
            return None
        node = node[seg]
    return node


def _set(out: dict[str, Any], path: str, value: Any) -> None:
    segs = path.split(".")
    node = out
    for seg in segs[:-1]:
        node = node.setdefault(seg, {})
    node[segs[-1]] = value


def _scope_state(state: dict[str, Any], prefixes: list[str]) -> dict[str, Any]:
    """Keep only the subtrees named by ``prefixes`` (dotted); everything else is out of view."""
    out: dict[str, Any] = {}
    for pfx in prefixes:
        val = _read(state, pfx)
        if val is not None:
            _set(out, pfx, copy.deepcopy(val))
    return out


def _path_visible(path: str, prefixes: list[str]) -> bool:
    return any(path == pfx or path.startswith(pfx + ".") for pfx in prefixes)


def _event_visible(rec: dict[str, Any], actor: str, scope: Scope) -> bool:
    if rec["actor"] == actor or rec["actor"] in scope.get("actors", []):
        return True
    prefixes = scope.get("paths", [])
    return any(_path_visible(d["path"], prefixes) for d in rec.get("delta") or [])


def _load_score(run_id: str, base_dir: str | Path) -> dict[str, Any] | None:
    path = Path(base_dir) / run_id / "score.json"
    return json.loads(path.read_text()) if path.exists() else None


def project(
    run_id: str,
    actor: str,
    at: int,
    scopes: Scopes | None = None,
    base_dir: str | Path = "runs",
) -> View:
    """Pure projection of the log at ``sim_time == at`` through ``actor``'s scope. Idempotent."""
    records = read_records(run_id, base_dir)
    seen = [r for r in records if int(r["sim_time"]) <= at]
    seq = max((int(r["seq"]) for r in seen), default=0)
    full_state = state_at(run_id, seq, base_dir).snapshot()

    if actor in OMNISCIENT:
        return View(actor, at, seq, full_state, seen)

    scope = (scopes or {}).get(actor, {})
    state = _scope_state(full_state, scope.get("paths", []))
    events = [r for r in seen if _event_visible(r, actor, scope)]
    extras: dict[str, Any] = {}
    if actor == "grader":  # grader also surfaces the score derivation over its fact-view
        score = _load_score(run_id, base_dir)
        if score is not None:
            extras["score"] = score
    return View(actor, at, seq, state, events, extras)
