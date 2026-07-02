"""Sampler determinism + bind constraints + key sensitivity (hypothesis over seeds).

Two `sample` calls on the same key are byte-identical; every accepted draw binds to eligible IDs
(`holder != agent`, role-set membership, distinct roles); and a change to seed / substrate_hash /
generator_version re-derives a different PRNG stream, so keys never collide.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from saasworld.engine.bind import bind
from saasworld.engine.sample import derive, sample
from saasworld.engine.substrate import load_substrate, load_template

pytestmark = pytest.mark.property

_SUB = load_substrate()
_TEMPLATE = load_template("hidden-critical-blocker")
_SEEDS = st.integers(min_value=0, max_value=2**31 - 1)


@settings(deadline=None, max_examples=100)
@given(seed=_SEEDS)
def test_sample_is_deterministic(seed: int) -> None:
    assert sample(_TEMPLATE, seed, _SUB.hash) == sample(_TEMPLATE, seed, _SUB.hash)


@settings(deadline=None, max_examples=100)
@given(seed=_SEEDS)
def test_bind_constraints_hold_on_every_accepted_draw(seed: int) -> None:
    draw = sample(_TEMPLATE, seed, _SUB.hash)
    binding = bind(_TEMPLATE, draw, _SUB, seed)
    holder = binding.ids["blocker.holder"]
    stakeholder = binding.ids["stakeholder"]
    assert holder != binding.agent
    assert _SUB.people[holder].role in {"backend", "fullstack", "sre"}
    assert _SUB.people[stakeholder].role in {"cto", "pm"}
    assert stakeholder != holder
    if draw["discovery.hops"] == 2:
        assert binding.pointer is not None


@settings(deadline=None, max_examples=100)
@given(seed=_SEEDS)
def test_a_changed_key_component_re_derives_the_stream(seed: int) -> None:
    base = derive(_TEMPLATE["archetype"], seed, _SUB.hash, "v1")
    assert base != derive(_TEMPLATE["archetype"], seed + 1, _SUB.hash, "v1")
    assert base != derive(_TEMPLATE["archetype"], seed, _SUB.hash + "x", "v1")
    assert base != derive(_TEMPLATE["archetype"], seed, _SUB.hash, "v2")
