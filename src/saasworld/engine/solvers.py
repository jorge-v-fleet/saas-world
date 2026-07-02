"""Reference solvers for the validity gate — they gate on the deterministic final SCORE only.

A **competent PM** drives the real graded moves (surface the blocker, reschedule, record the
go/no-go, tell the stakeholder) and must reach full score; a **busy/lazy** solver only chatters and
must score ~0. Both run rule-scripted at the Kernel/event level, so the gate stays deterministic and
offline. Discovery can optionally go through the NPC engine's parser in replay mode (no live call);
either way only the score — never the transcript — gates.
"""

from __future__ import annotations

import copy
from typing import Any

from ..actions.catalog import load_catalog
from ..actions.effects import bind_effect
from ..eval.score import score
from ..kernel import Kernel
from ..llm.parser import LLMParser
from ..npc.engine import NPCEngine
from ..scenario.loader import _DATA, _personas_by_org, _seed_world
from ..state.store import WorldState
from .assemble import FactMap

_CATALOG = load_catalog(_DATA / "actions.json")


def _driver(factmap: FactMap) -> tuple[Kernel, dict[str, Any]]:
    """A Kernel over the freshly-assembled world + an in-memory trajectory collecting its events."""
    seed_state = _seed_world(factmap.seed)
    world = WorldState()
    world.restore(seed_state)
    kernel = Kernel(world)
    events: list[dict[str, Any]] = []
    # Record the deltas the Kernel actually applied (handler events keep their effect off the
    # event payload) so the evaluator's projection sees every write, NPC reveals included.
    kernel.add_sink(lambda e, applied: events.append(
        {"seq": e.seq, "sim_time": e.sim_time, "actor": e.actor, "kind": e.kind,
         "payload": {"deltas": applied}}))
    trajectory = {
        "snapshots": [{"sim_time": 0, "seq": 0, "state": copy.deepcopy(seed_state)}],
        "events": events,
    }
    return kernel, trajectory


def _new_date(factmap: FactMap) -> str:
    return f"D{factmap.bindings['deadline_day'] + 3}T17:00"


def _attach_holder(kernel: Kernel, factmap: FactMap, parser: LLMParser) -> None:
    """Register the holder as a live NPC so an npc_reply can surface the blocker via a reveal."""
    holder = factmap.ids["blocker.holder"]
    base = _personas_by_org()[holder]
    overlay = factmap.overlay.get(factmap.bindings["holder_persona"], {})
    cfg = {k: v for k, v in base.items() if not k.startswith("_")}
    cfg.update({k: v for k, v in overlay.items() if not k.startswith("_")})
    engine = NPCEngine(parser=parser)
    engine.register_npc(cfg)
    engine.attach(kernel)


def competent_pm(
    factmap: FactMap, eval_json: dict[str, Any], parser: LLMParser | None = None
) -> float:
    """Full-credit trajectory: surface -> reschedule -> record go/no-go -> inform stakeholder."""
    kernel, traj = _driver(factmap)
    ids, b = factmap.ids, factmap.bindings
    blocker, project, stakeholder = b["blocker"], ids["critical_project"], ids["stakeholder"]
    new_date = _new_date(factmap)

    if parser is not None:  # surface through the NPC engine (parser replays from the cassette)
        _attach_holder(kernel, factmap, parser)
        kernel.schedule(50, ids["blocker.holder"], "npc_reply", {
            "npc": ids["blocker.holder"], "sender": factmap.agent,
            "body": "Is the PSP ready for Friday?", "args": {"refs": ["task.psp_integration"]}})
    else:  # surface exactly as the holder's reveal would (system-sourced, the only graded writer)
        kernel.schedule(50, "system", "reveal", {"deltas": [
            {"op": "set", "path": f"blockers.{blocker}.surfaced", "value": True}]})

    kernel.schedule(110, "system", "reschedule", {"deltas": [
        {"op": "set", "path": f"projects.{project}.launch_date", "value": new_date}]})
    decision, _ = bind_effect(_CATALOG["record_decision"], {
        "about": project, "type": "gonogo", "action": b["correct_set"][0],
        "new_date": new_date, "owner": ids["blocker.holder"]}, now=0)
    kernel.schedule(120, "agent", "record_decision", {"deltas": decision})
    kernel.schedule(130, "agent", "send_message", {"deltas": [
        {"op": "append", "path": "messages", "value": {
            "to": stakeholder, "body": f"{b['blocker_label']} blocks the launch.",
            "refs": [blocker]}}]})

    kernel.advance_until(200)
    return score(traj, eval_json).final


def lazy(factmap: FactMap, eval_json: dict[str, Any]) -> float:
    """Activity-only trajectory: chatter + a hand-set task status. Moves no graded field."""
    kernel, traj = _driver(factmap)
    channel = f"chan.{factmap.ids['critical_project'].split('.', 1)[-1]}"
    for i in range(5):
        kernel.schedule(100 + i, "agent", "send_message", {"deltas": [
            {"op": "append", "path": "messages", "value": {"to": channel, "body": f"update {i}"}}]})
    kernel.advance_until(200)
    return score(traj, eval_json).final
