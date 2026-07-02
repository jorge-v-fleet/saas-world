"""World State unit tests (no Kernel needed).

Full checklist:
- each delta op: set / append / inc / link / unlink
- snapshot/restore identity
- view(scope) projection (people/projects/channels filtering)
- denied-path guard: agent write to blockers.*.surfaced / tasks.*.blocked_by raises; system allowed
- path validation: writing an unknown/reserved partition raises
"""

from __future__ import annotations

import pytest

from saasworld.state.store import WorldState

pytestmark = pytest.mark.state


def test_set_and_read() -> None:
    s = WorldState({"tasks": {"T1": {"status": "open"}}})
    s.apply([{"op": "set", "path": "tasks.T1.status", "value": "done"}], source="system")
    assert s.read("tasks.T1.status") == "done"


def test_agent_cannot_write_denied_path() -> None:
    s = WorldState({"blockers": {"b1": {"surfaced": False}}})
    with pytest.raises(PermissionError):
        s.apply([{"op": "set", "path": "blockers.b1.surfaced", "value": True}], source="agent")


def test_snapshot_restore_identity() -> None:
    s = WorldState({"projects": {"p1": {"name": "checkout"}}})
    snap = s.snapshot()
    s.apply([{"op": "set", "path": "projects.p1.name", "value": "x"}], source="system")
    s.restore(snap)
    assert s.read("projects.p1.name") == "checkout"
