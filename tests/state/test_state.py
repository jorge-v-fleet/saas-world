"""World state: delta application, the constrained-write guard, and snapshot/restore."""

import pytest

from saasworld.state.store import WorldState

pytestmark = pytest.mark.state


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
