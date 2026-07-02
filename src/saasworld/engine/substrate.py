"""Read-only base packs the engine samples/binds against + the provenance substrate hash.

The engine reads `data/world` + `data/personas` + `data/templates`; it never writes them. The
substrate hash pins the base state the seed was resolved against — it enters both the PRNG
derivation and the provenance key, so a base edit re-derives a different (new) instance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..content_hash import sha256_hex, subtree_hash

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
WORLD = _DATA / "world"
PERSONAS = _DATA / "personas"
TEMPLATES = _DATA / "templates"

# org title -> the role token templates select on.
_TITLE_ROLE = {
    "CTO": "cto",
    "Product Manager": "pm",
    "Frontend Engineer": "frontend",
    "Backend Engineer": "backend",
    "Fullstack Engineer": "fullstack",
    "SRE / DevOps Engineer": "sre",
    "Product Designer": "designer",
}


@dataclass(frozen=True)
class Person:
    id: str
    name: str | None
    title: str
    role: str
    reports_to: str | None
    tier: str


@dataclass(frozen=True)
class Substrate:
    people: dict[str, Person]  # by org id
    persona_orgs: frozenset[str]  # org ids that have a base persona pack
    hash: str

    def agent_id(self) -> str:
        return next(p.id for p in self.people.values() if p.tier == "agent")

    def bindable(self, roles: set[str]) -> list[str]:
        """Active-tier, persona-backed org ids whose role is in `roles`, in a stable order."""
        return sorted(
            p.id
            for p in self.people.values()
            if p.tier == "active" and p.id in self.persona_orgs and p.role in roles
        )


def _read(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


@lru_cache(maxsize=1)
def load_substrate() -> Substrate:
    nodes = _read(WORLD / "org.json")["nodes"]
    people = {
        n["id"]: Person(
            id=n["id"],
            name=n.get("name"),
            title=n["title"],
            role=_TITLE_ROLE.get(n["title"], "other"),
            reports_to=n.get("reports_to"),
            tier=n["tier"],
        )
        for n in nodes
    }
    persona_orgs = frozenset(_read(p)["org_ref"] for p in sorted(PERSONAS.glob("*.json")))
    combined = f"world:{subtree_hash(WORLD)}\npersonas:{subtree_hash(PERSONAS)}"
    return Substrate(people=people, persona_orgs=persona_orgs, hash=sha256_hex(combined))


def load_template(archetype: str) -> dict[str, Any]:
    return _read(TEMPLATES / f"{archetype}.json")


def persona_id(org_id: str) -> str:
    """org.<x> -> npc.<x> (packs are keyed by structural id)."""
    return org_id.replace("org.", "npc.", 1)


def first_name(person: Person) -> str:
    return (person.name or person.id).split()[0]
