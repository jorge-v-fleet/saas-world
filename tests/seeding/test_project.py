"""project_eval: co-generate eval.json from the FactMap — weights, ID binding, derived sets."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from saasworld.engine.assemble import assemble
from saasworld.engine.bind import bind
from saasworld.engine.project import WeightsError, project_eval
from saasworld.engine.sample import sample
from saasworld.engine.substrate import Substrate

pytestmark = pytest.mark.seeding


def _factmap(template: dict[str, Any], substrate: Substrate, seed: int, **overrides: Any) -> Any:
    draw = sample(template, seed, substrate.hash)
    draw.update(overrides)
    binding = bind(template, draw, substrate, seed)
    return assemble(template, draw, binding, substrate)


def _weights(eval_json: dict[str, Any]) -> float:
    total = sum(p["w"] for cp in eval_json["checkpoints"] for p in cp["predicates"])
    return total + sum(p["w"] for p in eval_json["artifact_predicates"])


def test_weights_sum_to_one(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed)
    eval_json = project_eval(fm, template)
    assert _weights(eval_json) == pytest.approx(1.0)


def test_weights_off_by_a_hair_raises(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed)
    broken = copy.deepcopy(template)
    broken["eval_shapes"][0]["w"] = 0.40  # 1.10 total
    with pytest.raises(WeightsError):
        project_eval(fm, broken)


def test_predicates_bind_to_resolved_ids(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed)
    eval_json = project_eval(fm, template)
    world_ids = fm.world_ids()
    surfaced = eval_json["checkpoints"][0]["predicates"][0]["assert"]["path"]
    assert fm.bindings["blocker"] in surfaced
    assert fm.bindings["blocker"] in world_ids
    informed = eval_json["checkpoints"][0]["predicates"][3]["assert"]["exists"]
    assert fm.ids["stakeholder"] in informed and fm.ids["stakeholder"] in world_ids


def test_correct_action_set_tracks_movability(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    movable = project_eval(_factmap(template, substrate, golden_seed,
                                    **{"deadline.movable": True}), template)
    fixed = project_eval(_factmap(template, substrate, golden_seed,
                                  **{"deadline.movable": False}), template)
    m_set = movable["checkpoints"][0]["predicates"][2]["assert"]["in"]["set"]
    f_set = fixed["checkpoints"][0]["predicates"][2]["assert"]["in"]["set"]
    assert set(m_set) == {"reschedule", "hold_and_mitigate"}
    assert set(f_set) == {"hold_and_mitigate"}


def test_missing_id_reference_is_rejected(
    template: dict[str, Any], substrate: Substrate, golden_seed: int
) -> None:
    fm = _factmap(template, substrate, golden_seed)
    fm.seed["blockers"] = []  # drop the entity the predicates bind to
    with pytest.raises(ValueError, match="absent IDs"):
        project_eval(fm, template)
