"""Two-runs scoring over a Kernel-driven trajectory of the seeded checkout scenario.

Drives the trajectory at the stable Kernel/event level (not the live send_message/NPC surface):
a system-sourced reveal is the same delta an NPC produces, the decision goes through the real
record_decision effect, and the CTO message matches send_message's stored shape. Run A (real work)
scores 1.0; Run B (activity only) scores 0.0 — activity padding moves no graded field.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from saasworld.actions.catalog import load_catalog
from saasworld.actions.effects import bind_effect
from saasworld.eval.score import score
from saasworld.kernel import Kernel
from saasworld.scenario.loader import _DATA, load
from saasworld.state.store import WorldState

pytestmark = pytest.mark.integration

_CATALOG = load_catalog(_DATA / "actions.json")


def _seed_and_gt() -> tuple[dict[str, Any], dict[str, Any]]:
    """Seed the checkout world via the Loader (discarding its kernel), return (seed, eval_gt)."""
    k = Kernel(WorldState())
    loaded = load("checkout-not-ready", k)
    return k.state.snapshot(), loaded.eval_ground_truth


def _driver() -> tuple[Kernel, list[Any], dict[str, Any]]:
    """A fresh Kernel over the real seed, collecting applied events into an in-memory trajectory."""
    seed, gt = _seed_and_gt()
    world = WorldState()
    world.restore(seed)
    kernel = Kernel(world)
    events: list[Any] = []
    kernel.add_sink(lambda e, _deltas: events.append(e))
    trajectory = {"snapshots": [{"sim_time": 0, "seq": 0, "state": copy.deepcopy(seed)}],
                  "events": events}
    return kernel, events, trajectory | {"_gt": gt}


def _decision_deltas(**args: Any) -> list[dict[str, Any]]:
    deltas, _ = bind_effect(_CATALOG["record_decision"], args, now=0)
    return deltas


def test_run_a_real_work_scores_one() -> None:
    kernel, _events, traj = _driver()
    gt = traj.pop("_gt")
    # Surface the blocker exactly as an NPC reveal would (system-sourced, the only graded writer).
    kernel.schedule(100, "system", "reveal", {"deltas": [
        {"op": "set", "path": "blockers.blocker.psp_cert.surfaced", "value": True}]})
    # The reschedule outcome moves the launch date.
    kernel.schedule(110, "system", "reschedule", {"deltas": [
        {"op": "set", "path": "projects.proj.checkout.launch_date", "value": "D8T17:00"}]})
    # Record the go/no-go through the real record_decision effect.
    kernel.schedule(120, "agent", "record_decision", {"deltas": _decision_deltas(
        about="proj.checkout", type="gonogo", action="reschedule",
        new_date="D8T17:00", owner="org.be_b2")})
    # Inform the CTO with a message shaped like send_message's stored value.
    kernel.schedule(130, "agent", "send_message", {"deltas": [
        {"op": "append", "path": "messages",
         "value": {"to": "org.cto", "body": "PSP cert blocks Friday.",
                   "refs": ["blocker.psp_cert"]}}]})
    kernel.advance_until(200)

    result = score(traj, gt)
    assert result.final == pytest.approx(1.0)
    assert result.weights_sum == pytest.approx(1.0)
    assert all(r.status == "pass" for cp in result.checkpoints for r in cp.predicates)
    assert result.artifact_results[0].status == "pass"


def test_run_b_activity_only_scores_zero() -> None:
    kernel, _events, traj = _driver()
    gt = traj.pop("_gt")
    for i in range(5):  # padding: chatter, no reveal / no decision / no CTO ref
        kernel.schedule(100 + i, "agent", "send_message", {"deltas": [
            {"op": "append", "path": "messages",
             "value": {"to": "chan.checkout", "body": f"update {i}"}}]})
    # Hand-set a task status — allowed, but clears no blocker and touches no graded field.
    kernel.schedule(150, "agent", "update_task", {"deltas": [
        {"op": "set", "path": "tasks.task.psp_integration.status", "value": "done"}]})
    kernel.advance_until(200)

    result = score(traj, gt)
    assert result.final == pytest.approx(0.0)
    assert all(r.credit == 0.0 for cp in result.checkpoints for r in cp.predicates)
    assert result.artifact_results[0].status == "pending"
