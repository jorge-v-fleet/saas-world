"""Resolve abstract slots to real substrate IDs — only active-tier, persona-backed NPCs eligible.

Selection among eligible candidates is a seeded draw off a bind-salted stream (deterministic, no
ambient order dependence). Hard eligibility is re-checked against real IDs: `holder != agent`, the
holder's role is in the selector's set, and the stakeholder is distinct from the holder.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

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


def bind(template: dict[str, Any], draw: Draw, substrate: Substrate, seed: int) -> Binding:
    """Resolve holder / critical_project / stakeholder / pointer; collect the active set."""
    rng = _bind_rng(template, seed, substrate.hash)
    agent = substrate.agent_id()
    slots = template["slots"]

    holder_pool = substrate.bindable(_roles(slots["blocker.holder"]["sample_from"]))
    holder = _choose(rng, [c for c in holder_pool if c != agent], "blocker.holder")
    project = _choose(rng, sorted(template["world"]["projects"]), "critical_project")
    stake_pool = substrate.bindable(_roles(slots["stakeholder"]["sample_from"]))
    stakeholder = _choose(rng, [c for c in stake_pool if c != holder], "stakeholder")

    pointer: str | None = None
    if draw.get("discovery.hops") == 2:
        pointer = _choose(
            rng,
            sorted(p.id for p in substrate.people.values()
                   if p.tier == "active" and p.id in substrate.persona_orgs
                   and p.reports_to == agent),
            "pointer",
        )

    ids = {"blocker.holder": holder, "critical_project": project, "stakeholder": stakeholder}
    holder_mgr = substrate.people[holder].reports_to
    activate = [stakeholder]
    if holder_mgr and holder_mgr not in activate:
        activate.append(holder_mgr)
    if pointer and pointer not in activate:
        activate.append(pointer)
    if holder not in activate:
        activate.append(holder)
    return Binding(agent=agent, ids=ids, pointer=pointer, activate=activate)
