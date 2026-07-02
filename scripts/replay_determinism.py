"""Determinism target — run the checkout scenario twice with the same seed, prove replication.

Drives one fixed agent episode through the full stack (Tool API -> scenario loader -> NPC engine
-> single-writer Kernel -> Trajectory Store), persists each run's canonical event log + final
snapshot, then replays both offline and asserts they are byte-for-byte identical. Exits non-zero on
any divergence, so it doubles as a CI check.

    uv run python scripts/replay_determinism.py [--seed N] [--keep]
"""

from __future__ import annotations

import argparse
import difflib
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from saasworld.api.app import create_app
from saasworld.trajectory.replay import ReplayResult, replay
from saasworld.trajectory.store import open_run

RUN_ID = "replay-check"
SCENARIO = "checkout-not-ready"

# A fixed agent episode. No wall-clock and no ambient RNG anywhere in the stack, so replaying the
# same script over the same frozen scenario must yield identical bytes every time.
EPISODE: list[dict[str, Any]] = [
    # Ask the backend owner about payments with a structured intent -> reveals the hidden blocker.
    {"verb": "send_message", "args": {"to": "org.be_b2", "body": "PSP ready for Friday?",
                                      "intent": "ask_status", "refs": ["task.psp_integration"]}},
    {"verb": "wait", "args": {"duration": 120}},              # let the reply land (modal delay)
    {"verb": "record_decision", "args": {"about": "proj.checkout", "type": "gonogo",
                                         "action": "reschedule", "new_date": "D8T17:00",
                                         "owner": "org.be_b2"}},
    {"verb": "wait", "args": {"duration": 60}},
    {"verb": "get_tasks", "args": {}},                        # observe (no event) — clock still
]


def _rpc(client: TestClient, id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    body = {"jsonrpc": "2.0", "id": id, "method": method, "params": params}
    return client.post("/rpc", json=body).json()  # type: ignore[no-any-return]


def run_once(base_dir: Path, seed: int) -> tuple[str, ReplayResult]:
    """Load the scenario, drive the episode with the store attached, then replay from disk."""
    app = create_app()
    kernel = app.state.kernel
    world = app.state.world
    client = TestClient(app)

    loaded = _rpc(client, 0, "load_scenario", {"name": SCENARIO})["result"]
    manifest = {
        "run_id": RUN_ID, "scenario_id": SCENARIO, "instance_hash": "inst-replay",
        "action_space_version": "v1", "dataset_version": loaded["dataset_version"],
        "seed": seed, "agent_version": "replay-check", "sim_t0": 0, "started_at_seq": 0,
    }
    store = open_run(manifest, state=world, base_dir=base_dir)  # opening snapshot = seeded world
    kernel.add_sink(store.record)

    for i, action in enumerate(EPISODE, start=1):
        _rpc(client, i, "action", action)
    store.close_run({"total": 0.0})

    return loaded["dataset_version"], replay(RUN_ID, base_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42, help="seed recorded in both run manifests")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dirs for inspection")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="replay-check-"))
    try:
        dv_a, a = run_once(tmp / "a", args.seed)
        dv_b, b = run_once(tmp / "b", args.seed)

        log_ok = a.event_log == b.event_log
        state_ok = a.final_state == b.final_state
        version_ok = dv_a == dv_b
        ok = log_ok and state_ok and version_ok

        print(f"scenario:          {SCENARIO}")
        print(f"seed:              {args.seed}  (identical for both runs)")
        print(f"dataset_version:   {dv_a}")
        print(f"events recorded:   {len(a.records)}")
        print(f"model calls:       {a.model_calls}  (replay is fully offline)")
        print(f"event-log match:   {'PASS' if log_ok else 'FAIL'}")
        print(f"final-state match: {'PASS' if state_ok else 'FAIL'}")
        print(f"version match:     {'PASS' if version_ok else 'FAIL'}")

        if not log_ok:
            print("\n--- event-log diff (run a vs run b) ---")
            diff = difflib.unified_diff(
                a.event_log.splitlines(), b.event_log.splitlines(), "run_a", "run_b", lineterm=""
            )
            print("\n".join(diff))

        print("\nRESULT:", "✅ deterministic — two runs replicate byte-for-byte"
              if ok else "❌ NON-DETERMINISTIC — see diff above")
        if args.keep:
            print("run dirs kept at:", tmp)
        return 0 if ok else 1
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
