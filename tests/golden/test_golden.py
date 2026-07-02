"""Determinism: a fixed action script reproduces an identical event log and snapshot.

Flagship replay-grade proof. A FIXED script is driven through the JSON-RPC Tool API; the
canonical event log (every applied event, in order) plus the final world snapshot are captured
and asserted byte-identical to a stored golden. Two in-process runs must also match each other.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from saasworld.api.app import create_app

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).parent / "core_loop.json"

# Fixed, deterministic script: exercises all three clock classes (observe/mutate/advance)
# against the minimal bootstrap seed, avoiding any denied write or precondition failure.
SCRIPT: list[dict[str, Any]] = [
    {"verb": "read_inbox", "args": {}},
    {"verb": "get_people", "args": {}},
    {"verb": "create_task", "args": {"project": "proj.checkout", "title": "Payments API",
                                     "owner": "org.fe_a1"}},
    {"verb": "send_message", "args": {"to": "chan.checkout", "body": "status?"}},
    {"verb": "update_task", "args": {"task": "t1", "set": {"status": "in_progress"}}},
    {"verb": "record_decision", "args": {"about": "proj.checkout", "type": "gonogo",
                                         "action": "reschedule"}},
    {"verb": "wait", "args": {"duration": 60}},
]


def run_script(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Drive `actions` through /rpc on a fresh app; return {log, final}.

    log   = concatenation of every applied event (each response's events_since), in order.
    final = the final world snapshot (via the `snapshot` RPC method).
    """
    client = TestClient(create_app())
    log: list[dict[str, Any]] = []
    for action in actions:
        resp = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "action", "params": action},
        )
        result = resp.json()["result"]
        log.extend(result["events_since"])
    snap = client.post(
        "/rpc", json={"jsonrpc": "2.0", "id": 2, "method": "snapshot", "params": {}}
    ).json()["result"]
    return {"log": log, "final": snap}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2)


def test_core_loop_matches_golden(update_golden: bool) -> None:
    run = run_script(SCRIPT)
    text = _canonical(run)
    if update_golden:
        GOLDEN.write_text(text + "\n")
        return
    assert text + "\n" == GOLDEN.read_text()


def test_replay_is_byte_identical() -> None:
    """Two in-process runs of the same script are byte-for-byte identical (replay-grade)."""
    assert _canonical(run_script(SCRIPT)) == _canonical(run_script(SCRIPT))
