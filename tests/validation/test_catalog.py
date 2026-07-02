"""Action catalog: structural validation of data/actions.json + effect binding."""

import json
from pathlib import Path

import pytest

from saasworld.actions.catalog import CLOCK_CLASSES, load_catalog
from saasworld.actions.effects import bind_effect
from saasworld.state.guard import DENIED_PATHS
from saasworld.state.schema import CORE_PARTITIONS

pytestmark = pytest.mark.validation

CATALOG = Path(__file__).parents[2] / "data" / "actions.json"


def _write(tmp_path, entry):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"actions": [entry]}))
    return p


# --- happy path: the shipped catalog ----------------------------------------


def test_catalog_loads():
    cat = load_catalog(CATALOG)
    assert "send_message" in cat


def test_every_entry_well_formed():
    cat = load_catalog(CATALOG)
    for verb, entry in cat.items():
        assert entry["id"] == verb
        assert entry["class"] in CLOCK_CLASSES
        assert "args" in entry
        if entry["class"] == "mutate":
            assert isinstance(entry.get("effect"), list) and entry["effect"]


def test_effect_paths_reference_valid_partitions():
    cat = load_catalog(CATALOG)
    for entry in cat.values():
        for delta in entry.get("effect") or []:
            assert delta["path"].split(".", 1)[0] in CORE_PARTITIONS


def test_no_shipped_effect_writes_denied_path():
    cat = load_catalog(CATALOG)
    denied = set(DENIED_PATHS)
    for entry in cat.values():
        for delta in entry.get("effect") or []:
            assert delta["path"] not in denied


def test_observe_entries_have_no_effect():
    cat = load_catalog(CATALOG)
    for entry in cat.values():
        if entry["class"] == "observe":
            assert "effect" not in entry


def test_wait_has_no_deltas():
    cat = load_catalog(CATALOG)
    assert cat["wait"].get("effect") is None


# --- negative cases: the validator rejects malformed entries -----------------


def test_denied_path_effect_rejected(tmp_path):
    entry = {"id": "evil", "class": "mutate", "args": {},
             "effect": [{"op": "set", "path": "blockers.b1.surfaced", "value": True}]}
    with pytest.raises(ValueError):
        load_catalog(_write(tmp_path, entry))


def test_denied_blocked_by_rejected(tmp_path):
    entry = {"id": "evil", "class": "mutate", "args": {},
             "effect": [{"op": "set", "path": "tasks.T1.blocked_by", "value": "x"}]}
    with pytest.raises(ValueError):
        load_catalog(_write(tmp_path, entry))


def test_missing_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_catalog(_write(tmp_path, {"class": "observe", "args": {}}))


def test_bad_class_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_catalog(_write(tmp_path, {"id": "x", "class": "nope", "args": {}}))


def test_missing_args_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_catalog(_write(tmp_path, {"id": "x", "class": "observe"}))


def test_mutate_missing_effect_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_catalog(_write(tmp_path, {"id": "x", "class": "mutate", "args": {}}))


def test_invalid_partition_rejected(tmp_path):
    entry = {"id": "x", "class": "mutate", "args": {},
             "effect": [{"op": "append", "path": "nonsense", "value": {}}]}
    with pytest.raises(ValueError):
        load_catalog(_write(tmp_path, entry))


# --- effect binding ----------------------------------------------------------


def test_bind_substitutes_args():
    cat = load_catalog(CATALOG)
    deltas, follow = bind_effect(cat["send_message"], {"to": "sam", "body": "hi"}, now=0)
    assert follow == []
    assert deltas == [{"op": "append", "path": "messages",
                       "value": {"to": "sam", "body": "hi", "refs": None}}]


def test_bind_substitutes_nested_value():
    cat = load_catalog(CATALOG)
    deltas, _ = bind_effect(cat["send_message"],
                            {"to": "cto", "body": "fyi", "refs": ["blocker.psp"]}, now=0)
    assert deltas[0]["value"]["refs"] == ["blocker.psp"]


def test_bind_wait_yields_nothing():
    cat = load_catalog(CATALOG)
    assert bind_effect(cat["wait"], {"duration": 60}, now=0) == ([], [])


def test_bind_is_deterministic():
    cat = load_catalog(CATALOG)
    entry, args = cat["record_decision"], {"about": "p1", "type": "gonogo"}
    assert bind_effect(entry, args, now=0) == bind_effect(entry, args, now=999)
