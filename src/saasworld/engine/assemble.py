"""Materialize the concrete world (seed / overlay / timeline) from the draw + bound IDs.

Returns the single resolved FactMap that the eval projector also reads — that shared read is the
coupling that keeps world and grader from drifting. Everything here is pure substitution over the
template's authored blueprints; no randomness, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bind import Binding
from .render import substitute
from .sample import Draw
from .substrate import Substrate, first_name, persona_id

_ROLE_LABEL = {"cto": "CTO", "pm": "PM"}


@dataclass
class FactMap:
    draw: Draw
    ids: dict[str, str]
    bindings: dict[str, Any]
    agent: str
    activate: list[str]
    seed: dict[str, Any]
    overlay: dict[str, Any]
    timeline: dict[str, Any]

    def world_ids(self) -> set[str]:
        ids = {self.agent, *self.activate}
        for part in ("projects", "tasks", "blockers"):
            ids.update(e["id"] for e in self.seed.get(part, []))
        return ids


def _day(offset: str) -> int:
    return int(offset[1 : offset.index("T")])


def _content(template: dict[str, Any], btype: str) -> dict[str, Any]:
    """Type-specific blocker content, falling back to the generic `_default` block."""
    blocks = template["blockers"]
    block: dict[str, Any] = blocks.get(btype) or blocks["_default"]
    return block


def _bindings(
    template: dict[str, Any], draw: Draw, binding: Binding, substrate: Substrate
) -> dict[str, Any]:
    holder, stakeholder = binding.ids["blocker.holder"], binding.ids["stakeholder"]
    btype = draw["blocker.type"]
    content = _content(template, btype)
    blocker = substitute(content["blocker"]["id"], {"blocker_type": btype})
    movable = draw["deadline.movable"]
    offset = draw["deadline.offset"]
    day = _day(offset)
    correct_set = ["reschedule", "hold_and_mitigate"] if movable else ["hold_and_mitigate"]
    correct_why = (
        "acceptable-answer SET, not equality — set is derived from "
        f"launch_date_movable={str(movable).lower()} "
        + ("(movable -> reschedule preferred, hold acceptable)" if movable
           else "(fixed -> hold and mitigate)")
    )
    b: dict[str, Any] = {
        "agent": binding.agent,
        "holder": holder,
        "holder_persona": persona_id(holder),
        "holder_first": first_name(substrate.people[holder]),
        "holder_mgr": substrate.people[holder].reports_to,
        "stakeholder": stakeholder,
        "stakeholder_persona": persona_id(stakeholder),
        "stakeholder_label": _ROLE_LABEL.get(substrate.people[stakeholder].role, "stakeholder"),
        "critical_project": binding.ids["critical_project"],
        "blocker": blocker,
        "blocker_label": substitute(content["label"], {"blocker_type": btype}),
        "blocker_type": btype,
        "deadline_offset": offset,
        "deadline_day": day,
        "movable": movable,
        "task_due": f"D{day - 2}T17:00",
        "gonogo_due": f"D{day}T12:00",
        "correct_set": correct_set,
        "correct_why": correct_why,
        # No pointer NPC (1-hop): the agent owns the dependent task; no pointer overlay is emitted.
        "pointer": binding.pointer or binding.agent,
        "pointer_persona": persona_id(binding.pointer or binding.agent),
    }
    return b


def _distractors(template: dict[str, Any], b: dict[str, Any], n: int) -> list[dict[str, Any]]:
    proto = template.get("distractor_blocker")
    if not proto:
        return []
    out = []
    for i in range(n):
        d = substitute(proto, {**b, "n": i + 1})
        d["id"] = f"blocker.distractor_{i + 1}"
        out.append(d)
    return out


def assemble(
    template: dict[str, Any], draw: Draw, binding: Binding, substrate: Substrate
) -> FactMap:
    b = _bindings(template, draw, binding, substrate)
    content = _content(template, draw["blocker.type"])
    world = template["world"]

    critical = substitute(content["blocker"], b)
    blockers = [critical, *_distractors(template, b, int(draw.get("distractor_blockers", 0)))]

    seed = {
        "projects": [substitute(world["projects"][binding.ids["critical_project"]], b)],
        "tasks": substitute(world["tasks"], b),
        "blockers": blockers,
        "surfaces": substitute(world["surfaces"], b),
    }

    overlays = content["overlays"]
    overlay: dict[str, Any] = {
        b["holder_persona"]: substitute(overlays["holder"], b),
        b["stakeholder_persona"]: substitute(overlays["stakeholder"], b),
    }
    if binding.pointer:
        overlay[b["pointer_persona"]] = substitute(overlays["pointer"], b)

    scripted = list(substitute(template["timeline"]["scripted"], b))
    if draw.get("stakeholder.pressure") == "high" and "pressure_event" in template["timeline"]:
        scripted.append(substitute(template["timeline"]["pressure_event"], b))
    timeline = {"scripted": scripted}

    return FactMap(
        draw=draw, ids=binding.ids, bindings=b, agent=binding.agent,
        activate=binding.activate, seed=seed, overlay=overlay, timeline=timeline,
    )
