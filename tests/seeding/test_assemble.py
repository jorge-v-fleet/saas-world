"""assemble: materialize the FactMap — critical path, gated knowledge, discovery hops, timeline."""

from __future__ import annotations

from typing import Any

import pytest

from saasworld.engine.assemble import assemble
from saasworld.engine.bind import bind
from saasworld.engine.sample import sample
from saasworld.engine.substrate import Substrate

pytestmark = pytest.mark.seeding


def _factmap(template: dict[str, Any], substrate: Substrate, seed: int, **overrides: Any) -> Any:
    draw = sample(template, seed, substrate.hash)
    draw.update(overrides)
    binding = bind(template, draw, substrate, seed)
    return assemble(template, draw, binding, substrate)


def _by_id(items: list[dict[str, Any]], id_: str) -> dict[str, Any]:
    return next(i for i in items if i["id"] == id_)


def test_critical_path_is_wired(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed)
    holder = fm.ids["blocker.holder"]
    psp = _by_id(fm.seed["tasks"], "task.psp_integration")
    ui = _by_id(fm.seed["tasks"], "task.checkout_ui")
    blocker = fm.seed["blockers"][0]
    assert psp["owner"] == holder
    assert ui["depends_on"] == ["task.psp_integration"]
    assert blocker["affects"] == "task.psp_integration"
    assert blocker["surfaced"] is False
    assert blocker["known_to"] == [holder]
    assert blocker["severity"] == "launch_blocking"


def test_two_hop_adds_pointer_overlay(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed, **{"discovery.hops": 2})
    pointer_persona = fm.bindings["pointer_persona"]
    assert pointer_persona in fm.overlay
    item = fm.overlay[pointer_persona]["knowledge_scope"][0]
    assert item["links_blocker"] is None  # points at the holder, not the fact
    assert fm.bindings["holder_first"] in item["fact"]


def test_one_hop_omits_pointer_overlay(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed, **{"discovery.hops": 1})
    personas = set(fm.overlay)
    assert fm.bindings["holder_persona"] in personas
    assert fm.bindings["stakeholder_persona"] in personas
    assert len(personas) == 2


def test_distractors_are_emitted_off_the_critical_path(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed, **{"distractor_blockers": 2})
    blockers = fm.seed["blockers"]
    assert len(blockers) == 3
    critical = [b for b in blockers if b.get("severity") == "launch_blocking"]
    assert len(critical) == 1  # distractors never sit on the critical path


def test_timeline_holds_only_scripted_events(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed, **{"stakeholder.pressure": "high"})
    ids = [e["id"] for e in fm.timeline["scripted"]]
    assert ids == ["ev.standup", "ev.cto_checkin", "ev.cto_pressure"]
    low = _factmap(template, substrate, golden_seed, **{"stakeholder.pressure": "low"})
    assert [e["id"] for e in low.timeline["scripted"]] == ["ev.standup", "ev.cto_checkin"]
