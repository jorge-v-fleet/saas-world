"""Seeded slot sampling — the only place a seed is drawn. Pure in its arguments.

A single `random.Random` seeded off the whole provenance key drives every draw, so the same
`(template, seed, substrate, version)` yields a byte-identical `Draw` anywhere, and a change to any
key component re-derives a different stream. Inter-slot constraints are met by bounded rejection
sampling of the offending slot — never a Turing-complete DSL, never an unbounded loop.
"""

from __future__ import annotations

import random
from typing import Any

from ..content_hash import sha256_hex
from .types import GENERATOR_VERSION

Draw = dict[str, Any]

_MAX_TRIES = 64


class Unsatisfiable(RuntimeError):
    """A slot's constraint could not be met within the retry budget."""


def derive(template_id: str, seed: int, substrate_hash: str, generator_version: str) -> int:
    """Fold the provenance key into a PRNG seed; the seed alone never determines the stream."""
    key = f"{template_id}\x00{seed}\x00{substrate_hash}\x00{generator_version}"
    return int(sha256_hex(key), 16)


def rng_for(template: dict[str, Any], seed: int, substrate_hash: str) -> random.Random:
    return random.Random(
        derive(template["archetype"], seed, substrate_hash, GENERATOR_VERSION)
    )


def _sample_slots(template: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Enum/int slots in a fixed order (template slots, then the deadline offset)."""
    slots = [
        (name, spec)
        for name, spec in template.get("slots", {}).items()
        if "sample" in spec or "sample_int" in spec
    ]
    deadline = template.get("time", {}).get("deadline.offset")
    if deadline is not None:
        slots.append(("deadline.offset", deadline))
    return slots


def _draw_one(rng: random.Random, spec: dict[str, Any]) -> Any:
    if "sample_int" in spec:
        lo, hi = spec["sample_int"]
        return rng.randint(lo, hi)
    population = spec["sample"]
    weights = spec.get("weights")
    if weights:
        return rng.choices(population, weights=weights, k=1)[0]
    return rng.choice(population)


def _holds(constraint: str, name: str, draw: Draw) -> bool:
    """Evaluate a `<slot> (==|!=) <slot>` constraint over already-drawn *sample* slots.

    Constraints that reference a not-yet-resolved (bind) slot are deferred to bind and pass here.
    """
    for op in ("!=", "=="):
        if op in constraint:
            lhs, rhs = (s.strip() for s in constraint.split(op, 1))
            if lhs not in draw or rhs not in draw:
                return True
            equal = draw[lhs] == draw[rhs]
            return (not equal) if op == "!=" else equal
    return True


def sample(template: dict[str, Any], seed: int, substrate_hash: str) -> Draw:
    """Fill every enum/int slot from the seeded stream; satisfy constraints by rejection."""
    rng = rng_for(template, seed, substrate_hash)
    draw: Draw = {}
    for name, spec in _sample_slots(template):
        value = _draw_one(rng, spec)
        constraint = spec.get("constraint")
        tries = 0
        while constraint and not _holds(constraint, name, {**draw, name: value}):
            if tries >= _MAX_TRIES:
                raise Unsatisfiable(f"slot {name!r} constraint {constraint!r} unmet")
            value = _draw_one(rng, spec)
            tries += 1
        draw[name] = value
    return draw
