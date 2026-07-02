"""World state: delta application, the constrained-write guard, and snapshot/restore.

Checklist:
- each delta op: set / append / inc / link / unlink
- snapshot/restore identity (survives mutation)
- view(scope) projection: people/projects/channels filtering, unscoped omitted
- denied-path guard: agent blocked on blockers.*.surfaced and tasks.*.blocked_by; system allowed
- path validation: unknown / reserved partition raises ValueError
"""

import pytest

from saasworld.state.deltas import apply_delta
from saasworld.state.schema import validate_path
from saasworld.state.store import WorldState

pytestmark = pytest.mark.state


# --- existing tests (kept) ---------------------------------------------------

def test_set_and_read():
    s = WorldState({"tasks": {"T1": {"status": "open"}}})
    s.apply([{"op": "set", "path": "tasks.T1.status", "value": "done"}], source="system")
    assert s.read("tasks.T1.status") == "done"


def test_agent_cannot_write_denied_path():
    s = WorldState({"blockers": {"b1": {"surfaced": False}}})
    with pytest.raises(PermissionError):
        s.apply([{"op": "set", "path": "blockers.b1.surfaced", "value": True}], source="agent")


def test_snapshot_restore_identity():
    s = WorldState({"projects": {"p1": {"name": "checkout"}}})
    snap = s.snapshot()
    s.apply([{"op": "set", "path": "projects.p1.name", "value": "x"}], source="system")
    s.restore(snap)
    assert s.read("projects.p1.name") == "checkout"


# --- delta ops ---------------------------------------------------------------

def test_set_creates_intermediate_dicts():
    s = WorldState({})
    s.apply([{"op": "set", "path": "tasks.T1.status", "value": "open"}], source="system")
    assert s.read("tasks.T1.status") == "open"


def test_append_autocreates_list():
    data: dict = {}
    apply_delta(data, {"op": "append", "path": "messages.m1.refs", "value": "x"})
    apply_delta(data, {"op": "append", "path": "messages.m1.refs", "value": "y"})
    assert data["messages"]["m1"]["refs"] == ["x", "y"]


def test_append_on_nonlist_raises():
    data = {"tasks": {"T1": {"refs": "notalist"}}}
    with pytest.raises(ValueError):
        apply_delta(data, {"op": "append", "path": "tasks.T1.refs", "value": "z"})


def test_inc_defaults_to_zero_then_accumulates():
    data: dict = {}
    apply_delta(data, {"op": "inc", "path": "projects.p1.count", "value": 3})
    apply_delta(data, {"op": "inc", "path": "projects.p1.count", "value": 2})
    assert data["projects"]["p1"]["count"] == 5


def test_link_is_idempotent():
    data: dict = {}
    apply_delta(data, {"op": "link", "path": "tasks.T1.deps", "value": "d1"})
    apply_delta(data, {"op": "link", "path": "tasks.T1.deps", "value": "d1"})
    apply_delta(data, {"op": "link", "path": "tasks.T1.deps", "value": "d2"})
    assert data["tasks"]["T1"]["deps"] == ["d1", "d2"]


def test_unlink_removes_when_present_and_noop_otherwise():
    data = {"tasks": {"T1": {"deps": ["d1", "d2"]}}}
    apply_delta(data, {"op": "unlink", "path": "tasks.T1.deps", "value": "d1"})
    apply_delta(data, {"op": "unlink", "path": "tasks.T1.deps", "value": "absent"})
    assert data["tasks"]["T1"]["deps"] == ["d2"]


def test_unknown_op_raises():
    with pytest.raises(ValueError):
        apply_delta({}, {"op": "delete", "path": "tasks.T1", "value": None})


def test_malformed_path_raises():
    with pytest.raises(ValueError):
        apply_delta({}, {"op": "set", "path": "", "value": 1})


# --- snapshot / restore -------------------------------------------------------

def test_snapshot_is_deep_copy():
    s = WorldState({"tasks": {"T1": {"deps": ["a"]}}})
    snap = s.snapshot()
    s.apply([{"op": "append", "path": "tasks.T1.deps", "value": "b"}], source="system")
    assert snap["tasks"]["T1"]["deps"] == ["a"]  # snapshot unaffected by later mutation


def test_restore_of_snapshot_is_identity_after_mutation():
    s = WorldState({"tasks": {"T1": {"deps": ["a"]}}})
    snap = s.snapshot()
    s.apply([{"op": "append", "path": "tasks.T1.deps", "value": "b"}], source="system")
    s.restore(snap)
    # mutating post-restore must not touch the snapshot (independent copy)
    s.apply([{"op": "append", "path": "tasks.T1.deps", "value": "c"}], source="system")
    assert snap["tasks"]["T1"]["deps"] == ["a"]
    assert s.read("tasks.T1.deps") == ["a", "c"]


# --- view(scope) projection ---------------------------------------------------

def test_view_filters_by_scope_and_omits_unscoped():
    s = WorldState(
        {
            "org": {"p1": {"name": "Sam"}, "p2": {"name": "Priya"}, "p3": {"name": "CTO"}},
            "projects": {"proj1": {"x": 1}, "proj2": {"x": 2}},
            "chat": {"c1": {"m": []}, "c2": {"m": []}},
            "tasks": {"T1": {}},  # unscoped partition
        }
    )
    v = s.view({"people": ["p1", "p3"], "projects": ["proj2"], "channels": ["c1"]})
    assert v == {
        "org": {"p1": {"name": "Sam"}, "p3": {"name": "CTO"}},
        "projects": {"proj2": {"x": 2}},
        "chat": {"c1": {"m": []}},
    }
    assert "tasks" not in v


def test_view_omits_partition_when_scope_key_absent():
    s = WorldState({"org": {"p1": {}}, "projects": {"proj1": {}}})
    v = s.view({"people": ["p1"]})
    assert v == {"org": {"p1": {}}}


def test_view_skips_missing_ids():
    s = WorldState({"org": {"p1": {}}})
    v = s.view({"people": ["p1", "ghost"]})
    assert v == {"org": {"p1": {}}}


# --- denied-path guard --------------------------------------------------------

def test_agent_blocked_on_tasks_blocked_by():
    s = WorldState({"tasks": {"T1": {}}})
    with pytest.raises(PermissionError):
        s.apply([{"op": "link", "path": "tasks.T1.blocked_by", "value": "b1"}], source="agent")


def test_system_may_write_denied_paths():
    s = WorldState({"blockers": {"b1": {}}, "tasks": {"T1": {}}})
    s.apply([{"op": "set", "path": "blockers.b1.surfaced", "value": True}], source="system")
    s.apply([{"op": "link", "path": "tasks.T1.blocked_by", "value": "b1"}], source="system")
    assert s.read("blockers.b1.surfaced") is True
    assert s.read("tasks.T1.blocked_by") == ["b1"]


def test_agent_may_write_non_denied_paths():
    s = WorldState({"tasks": {"T1": {"status": "open"}}})
    s.apply([{"op": "set", "path": "tasks.T1.status", "value": "in_progress"}], source="agent")
    assert s.read("tasks.T1.status") == "in_progress"


def test_apply_propagates_and_does_not_partially_swallow():
    s = WorldState({"tasks": {"T1": {"status": "open"}}, "blockers": {"b1": {}}})
    deltas = [
        {"op": "set", "path": "tasks.T1.status", "value": "done"},
        {"op": "set", "path": "blockers.b1.surfaced", "value": True},  # denied for agent
    ]
    with pytest.raises(PermissionError):
        s.apply(deltas, source="agent")
    assert s.read("tasks.T1.status") == "done"  # first op applied before the raise


# --- path validation ----------------------------------------------------------

def test_validate_path_accepts_core_partition():
    validate_path("tasks.T1.status")  # no raise


def test_validate_path_rejects_unknown_partition():
    with pytest.raises(ValueError):
        validate_path("bogus.x")


def test_validate_path_rejects_reserved_partition():
    for reserved in ("cust.x", "fin.y", "seas.z"):
        with pytest.raises(ValueError):
            validate_path(reserved)


def test_apply_rejects_unknown_partition():
    s = WorldState({})
    with pytest.raises(ValueError):
        s.apply([{"op": "set", "path": "bogus.x", "value": 1}], source="system")
