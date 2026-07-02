"""Shared fixtures: hand-built WorldStates and in-memory trajectories for the Evaluator suite."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from saasworld.state.store import WorldState

# A seed the checkout scenario predicates read against.
SEED: dict[str, Any] = {
    "org": {"org.pm_a": {"title": "PM"}, "org.be_b2": {"title": "BE"}, "org.cto": {"title": "CTO"}},
    "projects": {"proj": {"checkout": {"launch_date": "D5T17:00", "launch_date_movable": True}}},
    "blockers": {"blocker": {"psp_cert": {"surfaced": False}}},
    "decisions": [],
    "messages": [],
}


@pytest.fixture
def seed() -> dict[str, Any]:
    return copy.deepcopy(SEED)


def mkstate(data: dict[str, Any]) -> WorldState:
    return WorldState(copy.deepcopy(data))


@pytest.fixture
def realwork_trajectory() -> dict[str, Any]:
    """A trajectory where the blocker surfaced, launch date moved, a go/no-go was recorded, and the
    CTO was informed — the real-work run that scores near 1.0."""
    return {
        "snapshots": [{"sim_time": 0, "seq": 0, "state": copy.deepcopy(SEED)}],
        "events": [
            _ev(1, 100, "system", [
                {"op": "set", "path": "blockers.blocker.psp_cert.surfaced", "value": True}]),
            _ev(2, 110, "system", [
                {"op": "set", "path": "projects.proj.checkout.launch_date", "value": "D8T17:00"}]),
            _ev(3, 120, "agent", [
                {"op": "append", "path": "decisions", "value": {
                    "about": "proj.checkout", "type": "gonogo", "action": "reschedule",
                    "new_date": "D8T17:00", "owner": "org.be_b2"}}]),
            _ev(4, 130, "agent", [
                {"op": "append", "path": "messages", "value": {
                    "to": "org.cto", "body": "PSP cert blocks Friday.",
                    "refs": ["blocker.psp_cert"]}}]),
        ],
    }


@pytest.fixture
def activity_trajectory() -> dict[str, Any]:
    """Activity-only: chatter + a hand-set task status; no reveal, no decision, no CTO ref."""
    return {
        "snapshots": [{"sim_time": 0, "seq": 0, "state": copy.deepcopy(SEED)}],
        "events": [
            _ev(1, 100, "agent", [{"op": "append", "path": "messages",
                                   "value": {"to": "chan.checkout", "body": "hi"}}]),
            _ev(2, 110, "agent", [{"op": "append", "path": "messages",
                                   "value": {"to": "chan.checkout", "body": "busy"}}]),
        ],
    }


def _ev(seq: int, sim_time: int, actor: str, deltas: list[dict[str, Any]]) -> dict[str, Any]:
    return {"seq": seq, "sim_time": sim_time, "actor": actor,
            "kind": actor, "payload": {"deltas": deltas}, "caused_by": None}
