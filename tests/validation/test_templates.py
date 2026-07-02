"""Every archetype template in data/templates/ is well-formed and self-consistent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from saasworld.engine.bind import _roles, bind
from saasworld.engine.sample import sample
from saasworld.engine.substrate import TEMPLATES, load_substrate

pytestmark = pytest.mark.validation

_TEMPLATES = sorted(TEMPLATES.glob("*.json"))
_SLOT_VALUES = ("blocker.type", "discovery.hops", "reveal.gate", "deadline.movable",
                "distractor_blockers", "stakeholder.pressure", "deadline.offset")


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.stem)
def test_template_has_required_sections(path: Path) -> None:
    t = _load(path)
    assert t.get("archetype") == path.stem
    assert t.get("invariants"), "invariants must be present"
    assert t.get("slots"), "slots must be present"
    assert t.get("eval_shapes"), "eval_shapes must be present"


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.stem)
def test_eval_weights_sum_to_one(path: Path) -> None:
    total = sum(float(s["w"]) for s in _load(path)["eval_shapes"])
    assert total == pytest.approx(1.0)


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.stem)
def test_selectors_reference_resolvable_roles(path: Path) -> None:
    substrate = load_substrate()
    for slot in _load(path)["slots"].values():
        selector = slot.get("sample_from")
        if selector and "role in" in selector:
            roles = _roles(selector)
            assert roles, f"unparsable selector {selector!r}"
            assert substrate.bindable(roles), f"no eligible NPC for {selector!r}"


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.stem)
def test_pinned_seed_reproduces_example_binding(path: Path) -> None:
    t = _load(path)
    eb = t.get("example_binding")
    if not eb or "_seed" not in eb:
        pytest.skip("no pinned example_binding seed")
    substrate = load_substrate()
    seed = int(eb["_seed"])
    draw = sample(t, seed, substrate.hash)
    binding = bind(t, draw, substrate, seed)
    for slot in _SLOT_VALUES:
        if slot in eb:
            assert draw.get(slot) == eb[slot], slot
    for abstract in ("blocker.holder", "critical_project", "stakeholder"):
        if abstract in eb:
            assert binding.ids[abstract] == eb[abstract], abstract


def test_constraints_are_satisfiable_expressions() -> None:
    # Any declared inter-slot constraint parses to a supported (==|!=) form.
    for path in _TEMPLATES:
        for name, slot in _load(path)["slots"].items():
            c = slot.get("constraint")
            if c is not None:
                assert re.search(r"(==|!=)", c), f"{name}: {c!r} is not a ref (in)equality"
