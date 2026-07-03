"""Tool API against the scenario loader's *nested* id keying — regression for three bugs a
random-policy sweep surfaced.

`test_toolapi.py` drives the `load_bootstrap` world, which keys entities flat (`projects` has the
literal key `'proj.checkout'`, `tasks` has `'t1'`). The scenario loader instead nests dotted ids by
segment (`projects['proj']['checkout']`, `tasks['task']['psp']`) — the form the grader reads. The
referential guards and `attend_meeting` must work under that shape too. Before the fix they didn't:
create_task/update_task rejected valid nested ids as "unknown", and attend_meeting raised an
unhandled KeyError (the advance path assumed a `duration` arg it doesn't carry) -> -32603.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from saasworld.actions.catalog import load_catalog
from saasworld.api.rpc import dispatch
from saasworld.kernel import Kernel
from saasworld.scenario.loader import offset_to_minutes
from saasworld.state.store import WorldState

pytestmark = pytest.mark.toolapi

_CATALOG = load_catalog(Path(__file__).resolve().parents[2] / "data" / "actions.json")


def _world() -> WorldState:
    """A world keyed exactly as scenario.loader._nest builds it from dotted ids."""
    return WorldState({
        "org": {"org.pm_a": {"title": "PM"}, "org.fe_a1": {"title": "FE"}},
        "projects": {"proj": {"checkout": {"name": "Checkout", "owner": "org.pm_a"}}},
        "tasks": {"task": {"psp": {"project": "proj.checkout", "status": "todo"}}},
        "calendar": [{"id": "evt.standup", "start": "D1T09:30", "duration": 30,
                      "attendees": ["org.pm_a", "org.fe_a1"]}],
        "chat": {}, "messages": [], "decisions": [], "docs": [], "email": [],
    })


def _act(verb: str, args: dict) -> dict:
    w = _world()
    reply = dispatch(Kernel(w), w, _CATALOG, "action", {"verb": verb, "args": args})
    return reply | {"_world": w}


# --- create_task / update_task accept nested ids, reject unknown ---------------


def test_create_task_accepts_nested_project_id():
    r = _act("create_task", {"project": "proj.checkout", "title": "x", "owner": "org.fe_a1"})
    assert r["result"]["ok"]


def test_create_task_rejects_unknown_project():
    r = _act("create_task", {"project": "proj.ghost", "title": "x", "owner": "org.fe_a1"})
    assert r["error"]["code"] == 1001


def test_update_task_accepts_nested_task_id_and_writes_field():
    r = _act("update_task", {"task": "task.psp", "set": {"status": "done"}})
    assert r["result"]["ok"]
    assert r["_world"].read("tasks.task.psp.status") == "done"


def test_update_task_rejects_unknown_task():
    r = _act("update_task", {"task": "task.nope", "set": {"status": "done"}})
    assert r["error"]["code"] == 1001


# --- attend_meeting: no crash; releases the clock across the window -----------


def test_attend_meeting_advances_to_window_end():
    r = _act("attend_meeting", {"meeting": "evt.standup"})
    assert "result" in r  # was -32603 (unhandled KeyError) before the fix
    assert r["result"]["sim_time"] == offset_to_minutes("D1T09:30") + 30


def test_attend_meeting_unknown_meeting_is_precondition_error():
    r = _act("attend_meeting", {"meeting": "evt.nope"})
    assert r["error"]["code"] == 1001


def test_attend_meeting_non_attendee_is_precondition_error():
    w = WorldState({"org": {"org.pm_a": {}},
                    "calendar": [{"id": "evt.private", "start": "D1T10:00",
                                  "attendees": ["org.fe_a1"]}]})
    reply = dispatch(Kernel(w), w, _CATALOG, "action",
                     {"verb": "attend_meeting", "args": {"meeting": "evt.private"}})
    assert reply["error"]["code"] == 1001
