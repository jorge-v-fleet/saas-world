"""bind: abstract slots -> real active-tier substrate IDs, with eligibility enforced."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from saasworld.engine.bind import Unsatisfiable, bind
from saasworld.engine.sample import sample
from saasworld.engine.substrate import Substrate

pytestmark = pytest.mark.seeding


def test_holder_is_active_persona_backed_and_not_agent(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    draw = sample(template, golden_seed, substrate.hash)
    binding = bind(template, draw, substrate, golden_seed)
    holder = binding.ids["blocker.holder"]
    person = substrate.people[holder]
    assert person.tier == "active"
    assert holder in substrate.persona_orgs
    assert person.role in {"backend", "fullstack", "sre"}
    assert holder != binding.agent


def test_stakeholder_role_constrained_and_distinct(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    draw = sample(template, golden_seed, substrate.hash)
    binding = bind(template, draw, substrate, golden_seed)
    stakeholder = binding.ids["stakeholder"]
    assert substrate.people[stakeholder].role in {"cto", "pm"}
    assert stakeholder != binding.ids["blocker.holder"]


def test_critical_project_resolves_to_a_real_project(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    draw = sample(template, golden_seed, substrate.hash)
    binding = bind(template, draw, substrate, golden_seed)
    assert binding.ids["critical_project"] in template["world"]["projects"]


def test_two_hop_pointer_is_an_agent_report(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    draw = sample(template, golden_seed, substrate.hash)
    assert draw["discovery.hops"] == 2
    binding = bind(template, draw, substrate, golden_seed)
    assert binding.pointer is not None
    assert substrate.people[binding.pointer].reports_to == binding.agent


def test_empty_candidate_set_raises_unsatisfiable(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    draw = sample(template, golden_seed, substrate.hash)
    broken = copy.deepcopy(template)
    broken["slots"]["blocker.holder"]["sample_from"] = "active npcs where role in [ceo]"
    with pytest.raises(Unsatisfiable):
        bind(broken, draw, substrate, golden_seed)
