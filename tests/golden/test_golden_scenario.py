"""Determinism: a fixed load + discover script reproduces an identical event log and snapshot.

Extends the core-loop golden to the scenario/NPC path: load the frozen instance, ask Priya directly,
advance, and capture the canonical event log plus final world snapshot byte-for-byte.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from saasworld.api.app import create_app

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).parent / "scenario_discover.json"

SCRIPT: list[dict[str, Any]] = [
    {"verb": "send_message", "args": {"to": "org.be_b2", "body": "Is the PSP ready for Friday?",
                                      "refs": ["task.psp_integration"]}},
    {"verb": "wait", "args": {"duration": 120}},
    {"verb": "record_decision", "args": {"about": "proj.checkout", "type": "gonogo",
                                         "action": "reschedule"}},
]


def run_script(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Load the scenario, drive `actions` through /rpc, return {log, final}."""
    client = TestClient(create_app())
    client.post("/rpc", json={"jsonrpc": "2.0", "id": 0, "method": "load_scenario",
                              "params": {"name": "checkout-not-ready"}})
    log: list[dict[str, Any]] = []
    for action in actions:
        resp = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "action",
                                         "params": action})
        log.extend(resp.json()["result"]["events_since"])
    snap = client.post("/rpc", json={"jsonrpc": "2.0", "id": 2, "method": "snapshot",
                                     "params": {}}).json()["result"]
    return {"log": log, "final": snap}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2)


def test_scenario_discover_matches_golden(update_golden: bool) -> None:
    run = run_script(SCRIPT)
    text = _canonical(run)
    if update_golden:
        GOLDEN.write_text(text + "\n")
        return
    assert text + "\n" == GOLDEN.read_text()


def test_scenario_replay_is_byte_identical() -> None:
    assert _canonical(run_script(SCRIPT)) == _canonical(run_script(SCRIPT))
