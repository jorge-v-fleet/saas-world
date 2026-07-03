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
from .render import substitute

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


def _env(factmap: FactMap) -> dict[str, Any]:
    """Substitution bindings for a solver script: the bound ids/slots plus derived solver tokens."""
    env = {**factmap.ids, **factmap.bindings}
    env["solver_new_date"] = _new_date(factmap)
    env["correct_action"] = factmap.bindings["correct_set"][0]
    env["chat_channel"] = f"chan.{factmap.ids['critical_project'].split('.', 1)[-1]}"
    return env


def _run_script(
    factmap: FactMap, eval_json: dict[str, Any], steps: list[dict[str, Any]],
    parser: LLMParser | None = None,
) -> float:
    """Run an ordered step script on a fresh Kernel and return its deterministic final score."""
    kernel, traj = _driver(factmap)
    env = _env(factmap)
    for step in (substitute(raw, env) for raw in steps):
        if "advance_until" in step:
            kernel.advance_until(step["advance_until"])
        elif step.get("kind") == "npc_reply":
            if parser is not None:  # surface through the NPC engine (parser replays the cassette)
                _attach_holder(kernel, factmap, parser)
                kernel.schedule(step["at"], factmap.ids["blocker.holder"], "npc_reply", {
                    "npc": step["npc"], "sender": factmap.agent,
                    "body": step["body"], "args": step["args"]})
            else:  # surface exactly as the holder's reveal would (system is the only graded writer)
                kernel.schedule(step["at"], "system", "reveal", {"deltas": step["fallback_deltas"]})
        elif "verb" in step:
            deltas, _ = bind_effect(_CATALOG[step["verb"]], step.get("args", {}), now=0)
            kernel.schedule(step["at"], step["actor"], step["verb"], {"deltas": deltas})
        else:  # raw system-sourced deltas
            kernel.schedule(step["at"], step["actor"], step["kind"], {"deltas": step["deltas"]})
    return score(traj, eval_json).final


def competent_pm(
    factmap: FactMap, eval_json: dict[str, Any], parser: LLMParser | None = None
) -> float:
    """Full-credit trajectory: surface -> reschedule -> record go/no-go -> inform stakeholder."""
    return _run_script(factmap, eval_json, factmap.solvers["competent"], parser)


def lazy(factmap: FactMap, eval_json: dict[str, Any]) -> float:
    """Activity-only trajectory: chatter to the project channel. Moves no graded field."""
    return _run_script(factmap, eval_json, factmap.solvers["lazy"])
