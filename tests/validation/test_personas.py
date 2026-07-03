"""Base persona packs: the newly-onlined Sales + CS branches load and resolve to active NPCs."""

import json
from pathlib import Path

import pytest

from saasworld.engine.substrate import load_substrate, persona_id

pytestmark = pytest.mark.validation

PERSONAS = Path(__file__).parents[2] / "data" / "personas"
# Org nodes promoted reference->active in this experiment.
ONLINED = ["org.head_sales", "org.ae_1", "org.cs_mgr_1", "org.cs_1"]
EXPECTED_ROLE = {"org.head_sales": "sales", "org.ae_1": "sales",
                 "org.cs_mgr_1": "cs", "org.cs_1": "cs"}


def _pack(org_id: str) -> dict:
    return json.loads((PERSONAS / f"{persona_id(org_id)}.json").read_text())


@pytest.mark.parametrize("org_id", ONLINED)
def test_new_pack_is_well_formed(org_id: str) -> None:
    pack = _pack(org_id)
    assert pack["id"] == persona_id(org_id)
    assert pack["org_ref"] == org_id
    assert pack["tier"] == "active"
    for field in ("name", "title", "reports_to"):
        assert pack["identity"][field]
    assert pack["voice"]
    assert isinstance(pack["allowed_intents"], list) and pack["allowed_intents"]
    for key in ("people", "projects", "channels"):
        assert isinstance(pack["view_scope"][key], list)
    behavior = pack["behavior"]
    assert behavior["response_delay"]["mode_min"] > 0
    assert behavior["wakeup_cadence"]["every_sim_hours"] > 0
    assert behavior["wakeup_cadence"]["action"] == "replan_against_goals"


@pytest.mark.parametrize("org_id", ONLINED)
def test_onlined_node_resolves_to_active_npc(org_id: str) -> None:
    substrate = load_substrate()
    person = substrate.people[org_id]
    assert person.tier == "active"
    assert person.name  # named, not a bare reference node
    assert person.role == EXPECTED_ROLE[org_id]
    assert org_id in substrate.persona_orgs  # backed by a base pack


def test_role_tokens_are_bindable() -> None:
    substrate = load_substrate()
    assert set(substrate.bindable({"sales"})) == {"org.ae_1", "org.head_sales"}
    assert set(substrate.bindable({"cs"})) == {"org.cs_1", "org.cs_mgr_1"}
