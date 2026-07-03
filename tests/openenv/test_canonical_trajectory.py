"""Canonical kernel event log: the GET /trajectory endpoint, the write_run(canonical=...) files,
and a replay round-trip (opening snapshot + events.jsonl deltas -> the env's final state).

This is the durable form the future "Replay timeline" tool reconstructs world state from; it is
complementary to the policy action-stream (`trajectory.jsonl`), which is left untouched here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from saasworld.openenv import SaasWorldAction, SaasWorldEnvironment, create_env_app
from saasworld.trajectory.actionlog import EVENTS_FILE, write_run
from saasworld.trajectory.replay import state_at

pytestmark = pytest.mark.openenv

DISCOVER = SaasWorldAction("send_message", {
    "to": "org.be_b2", "body": "Is the PSP ready for Friday?", "refs": ["task.psp_integration"]})
WAIT = SaasWorldAction("wait", {"duration": 120})
DECIDE = SaasWorldAction("record_decision", {"about": "proj.checkout", "type": "gonogo",
                         "action": "reschedule", "new_date": "D8T17:00", "owner": "org.be_b2"})


def _delta_events(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in canonical["events"] if (e["payload"] or {}).get("deltas")]


def test_get_trajectory_returns_opening_snapshot_and_events_with_deltas() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(create_env_app())
    client.post("/reset", json={"scenario": "checkout-not-ready"})
    client.post("/step", json={"action": DISCOVER.to_dict()})
    client.post("/step", json={"action": WAIT.to_dict()})

    traj = client.get("/trajectory").json()
    assert traj["snapshots"][0]["seq"] == 0
    assert traj["snapshots"][0]["state"]["projects"]              # opening world present
    assert len(traj["events"]) >= 1
    assert _delta_events(traj)                                    # at least one carries a delta


def test_write_run_canonical_writes_events_and_opening_snapshot(tmp_path: Path) -> None:
    env = SaasWorldEnvironment()
    env.reset("checkout-not-ready")
    env.step(DISCOVER)
    env.step(WAIT)
    canonical = env.canonical_trajectory()

    out = write_run(tmp_path / "run", manifest={"run_id": "r1"}, rows=[], canonical=canonical)
    assert (out / "trajectory.jsonl").exists()                   # action stream untouched (empty)

    lines = [json.loads(x) for x in (out / EVENTS_FILE).read_text().splitlines() if x]
    assert lines and any(row["delta"] for row in lines)          # top-level delta field present
    row = next(r for r in lines if r["delta"])
    assert set(row) == {"seq", "sim_time", "actor", "kind", "payload", "delta", "caused_by"}

    snap = json.loads((out / "snapshots" / "0.json").read_text())
    assert snap["seq"] == 0 and snap["state"]["projects"]


def test_replay_round_trip_reconstructs_env_final_state(tmp_path: Path) -> None:
    """snapshots/0.json + events.jsonl deltas, replayed via trajectory/replay.state_at, must equal
    the env's final snapshot. We stage the canonical log as a store-shaped run dir (events.jsonl ->
    trajectory.jsonl) so replay.py's real reconstruction path is exercised unchanged."""
    env = SaasWorldEnvironment()
    env.reset("checkout-not-ready")
    for act in (DISCOVER, WAIT, DECIDE, WAIT):
        final = env.step(act)
    canonical = env.canonical_trajectory()

    write_run(tmp_path / "run", manifest={"run_id": "r1"}, rows=[], canonical=canonical)

    # Stage a replay-compatible run dir: replay reads trajectory.jsonl + snapshots/, and our
    # events.jsonl lines are already the store envelope shape replay expects.
    replay_dir = tmp_path / "runs" / "r1"
    (replay_dir / "snapshots").mkdir(parents=True)
    (replay_dir / "snapshots" / "0.json").write_text(
        (tmp_path / "run" / "snapshots" / "0.json").read_text())
    (replay_dir / "trajectory.jsonl").write_text(
        (tmp_path / "run" / EVENTS_FILE).read_text())

    last_seq = canonical["events"][-1]["seq"]
    rebuilt = state_at("r1", last_seq, base_dir=tmp_path / "runs").snapshot()
    assert rebuilt == final.state
