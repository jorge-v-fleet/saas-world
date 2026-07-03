"""Proactive/autonomous NPC wake-ups: opt-in scheduling, goal-gated outreach, cap, work-hours.

The wake-up path is DEFAULT OFF — existing scenarios don't set `autonomous_npcs`, so nothing is
scheduled and their dynamics are unchanged. When on, an NPC whose goal is unmet chases the agent
on a cadence, bounded by a per-NPC cap and work hours, and stops once world state satisfies it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from saasworld.kernel import Kernel
from saasworld.npc.engine import NPCEngine
from saasworld.scenario.loader import _schedule_wakeups, load, offset_to_minutes
from saasworld.state.store import WorldState

pytestmark = pytest.mark.npc

SCENARIO = Path(__file__).resolve().parents[2] / "data" / "scenarios" / "checkout-not-ready"
_HORIZON = 3 * 24 * 60  # 3 sim days in minutes


def _npc(**cadence: Any) -> dict[str, Any]:
    base = {"every_sim_hours": 2, "action": "replan_against_goals", "intent": "apply_pressure",
            "about": "deal", "max_proactive": 3,
            "satisfied_when": {"path": "projects.deal.stage", "eq": "committed"}}
    base.update(cadence)
    return {
        "org_ref": "org.head_sales",
        "identity": {"name": "Dana Sales"},
        "allowed_intents": ["ask_status", "apply_pressure"],
        "view_scope": {"projects": ["deal"]},
        "behavior": {"work_hours": {"start": "09:00", "end": "17:00"}, "wakeup_cadence": base},
    }


def _kernel(stage: str = "open") -> tuple[Kernel, NPCEngine]:
    k = Kernel(WorldState({"projects": {"deal": {"stage": stage}}, "messages": []}))
    engine = NPCEngine()
    engine.register_npc(_npc())
    engine.attach(k)
    return k, engine


def _proactive(k: Kernel) -> list[dict[str, Any]]:
    return [m for m in k.state.read("messages") if m.get("kind") == "proactive"]


def _drive(k: Kernel, horizon: int, step: int = 60) -> None:
    """Step the clock like a real episode: each tick drains the wakeup self-rescheduled last tick
    (the kernel fires events scheduled during apply on the NEXT advance, a tested invariant)."""
    t = k.now()
    while t < horizon:
        t = min(t + step, horizon)
        k.advance_until(t)


# --- OFF by default: existing scenarios are untouched ------------------------


def test_off_by_default_schedules_no_wakeups():
    k = Kernel(WorldState())
    load(SCENARIO, k)  # checkout-not-ready sets no flag
    assert len(k.queue) == 3  # only the 3 scripted timeline entries — zero wakeups
    fired = k.advance_until(offset_to_minutes("D5T23:59"))
    assert all(e.kind != "npc_wakeup" for e in fired)
    assert _proactive(k) == []


# --- ON: opt-in scheduling in the loader ------------------------------------


def test_loader_flag_gates_scheduling():
    engine = NPCEngine()
    engine.register_npc(_npc())
    manifest = {"activate": ["org.head_sales"], "time": {"horizon_days": 3}}
    k = Kernel(WorldState())
    _schedule_wakeups(k, engine, manifest)  # flag absent
    assert len(k.queue) == 0
    _schedule_wakeups(k, engine, {**manifest, "autonomous_npcs": True})
    assert len(k.queue) == 1
    ev = k.queue.pop_due(_HORIZON)[0]
    assert ev.kind == "npc_wakeup" and ev.sim_time == 120  # first tick one cadence in
    assert ev.payload == {"npc": "org.head_sales", "horizon": _HORIZON}


# --- ON: proactive outreach, capped, deterministic --------------------------


def test_unsatisfied_goal_emits_capped_proactive_messages():
    k, _ = _kernel(stage="open")
    k.schedule(540, "org.head_sales", "npc_wakeup",
               {"npc": "org.head_sales", "horizon": _HORIZON})  # 09:00 D1
    _drive(k, _HORIZON)
    msgs = _proactive(k)
    assert len(msgs) == 3  # max_proactive cap holds; no infinite chase
    assert all(m["from"] == "org.head_sales" and m["to"] == "org.pm_a" for m in msgs)
    assert all(m["intent"] == "apply_pressure" and m["about"] == "deal" for m in msgs)
    assert len(k.queue) == 0  # stopped rescheduling at the cap


def test_wakeup_outside_work_hours_defers_without_acting():
    k, _ = _kernel(stage="open")
    k.schedule(420, "org.head_sales", "npc_wakeup",
               {"npc": "org.head_sales", "horizon": _HORIZON})  # 07:00 D1 — before 09:00
    k.advance_until(420)
    assert _proactive(k) == []  # did not act outside hours
    assert len(k.queue) == 1  # slid to the next work-hours start instead
    assert k.queue.pop_due(_HORIZON)[0].sim_time == 540  # 09:00


def test_satisfied_goal_stays_silent_and_stops():
    k, _ = _kernel(stage="committed")  # goal already met via world state
    k.schedule(540, "org.head_sales", "npc_wakeup",
               {"npc": "org.head_sales", "horizon": _HORIZON})
    k.advance_until(_HORIZON)
    assert _proactive(k) == []
    assert len(k.queue) == 0  # no reschedule once satisfied


def test_proactive_writes_are_npc_sourced_not_denied():
    # Outreach flows the normal messages path as the NPC actor; it never touches a graded field.
    k, _ = _kernel(stage="open")
    k.schedule(540, "org.head_sales", "npc_wakeup",
               {"npc": "org.head_sales", "horizon": _HORIZON})
    _drive(k, _HORIZON)
    assert _proactive(k)  # outreach happened
    assert k.state.read("projects.deal.stage") == "open"  # but no goal/graded-field mutation


def test_wakeups_are_deterministic():
    def run() -> list[dict[str, Any]]:
        k, _ = _kernel(stage="open")
        k.schedule(540, "org.head_sales", "npc_wakeup",
                   {"npc": "org.head_sales", "horizon": _HORIZON})
        _drive(k, _HORIZON)
        return _proactive(k)

    assert run() == run()
