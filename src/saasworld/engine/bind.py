"""Resolve template-declared entity slots to real substrate IDs — a generic, seeded interpreter.

Each `bind_order` slot names a `sample_from` selector (a substrate query) and an optional inter-slot
`constraint`; candidates are drawn from a bind-salted stream in the declared order, so the same
`(template, seed, substrate)` always resolves the same IDs. Eligibility (active tier, persona
backing, role/report membership, distinctness) rides on the selector + constraint — no archetype
name appears here.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

from .render import cond, substitute
from .sample import Draw, derive
from .substrate import Substrate
from .types import GENERATOR_VERSION


class Unsatisfiable(RuntimeError):
    """A selector had no eligible candidate — bubbles up to trigger a resample."""


@dataclass
class Binding:
    agent: str
    ids: dict[str, str]  # abstract slot -> substrate id
    pointer: str | None
    activate: list[str] = field(default_factory=list)


def _roles(selector: str) -> set[str]:
    m = re.search(r"role in \[([^\]]+)\]", selector)
    return {r.strip() for r in m.group(1).split(",")} if m else set()


def _bind_rng(template: dict[str, Any], seed: int, substrate_hash: str) -> random.Random:
    return random.Random(
        derive(template["archetype"] + ":bind", seed, substrate_hash, GENERATOR_VERSION)
    )


def _choose(rng: random.Random, candidates: list[str], what: str) -> str:
    if not candidates:
        raise Unsatisfiable(f"no eligible candidate for {what}")
    return rng.choice(candidates)


def _candidates(
    selector: str, substrate: Substrate, template: dict[str, Any], agent: str
) -> list[str]:
    """Substrate ids a selector admits, in a stable order (the draw list)."""
    if "role in [" in selector:
        return substrate.bindable(_roles(selector))
    if "reports_to agent" in selector:
        return sorted(
            p.id for p in substrate.people.values()
            if p.tier == "active" and p.id in substrate.persona_orgs and p.reports_to == agent
        )
    if selector.lstrip().startswith("projects"):
        return sorted(template["world"]["projects"])
    raise Unsatisfiable(f"unrecognized selector {selector!r}")


def _apply(
    constraint: str | None, cands: list[str], bound: dict[str, str], agent: str
) -> list[str]:
    """Filter candidates by a `<slot> (==|!=) <slot|agent>` constraint against already-bound ids."""
    if not constraint:
        return cands
    m = re.match(r"\s*\S+\s*(==|!=)\s*(\S+)\s*$", constraint)
    if not m:
        return cands
    op, rhs = m.group(1), m.group(2)
    val = agent if rhs == "agent" else bound[rhs]
    return [c for c in cands if (c == val) == (op == "==")]


def _activate(
    spec: list[str], bound: dict[str, str], pointer: str | None, substrate: Substrate
) -> list[str]:
    """Ordered, de-duped active set from a template rule (tokens: bound aliases + `<alias>_mgr`)."""
    env: dict[str, Any] = {**bound, "pointer": pointer}
    for alias, cid in list(bound.items()):
        person = substrate.people.get(cid)
        if person is not None:
            env[f"{alias}_mgr"] = person.reports_to
    out: list[str] = []
    for tok in spec:
        val = substitute(tok, env)
        if val and val not in out:
            out.append(val)
    return out


def bind(template: dict[str, Any], draw: Draw, substrate: Substrate, seed: int) -> Binding:
    """Resolve every declared entity slot in `bind_order`; collect the active set."""
    rng = _bind_rng(template, seed, substrate.hash)
    agent = substrate.agent_id()
    slots = template["slots"]
    bound: dict[str, str] = {}  # alias -> id (for constraint refs + activate)
    ids: dict[str, str] = {}
    pointer: str | None = None
    for name in template["bind_order"]:
        spec = slots[name]
        when = spec.get("when")
        if when and not cond(when, draw):
            continue
        cands = _apply(
            spec.get("constraint"),
            _candidates(spec["sample_from"], substrate, template, agent), bound, agent,
        )
        chosen = _choose(rng, cands, name)
        bound[spec["as"]] = chosen
        if spec.get("into") == "pointer":
            pointer = chosen
        else:
            ids[name] = chosen
    return Binding(
        agent=agent, ids=ids, pointer=pointer,
        activate=_activate(template["activate"], bound, pointer, substrate),
    )
