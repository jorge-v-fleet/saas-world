"""Replay-timeline plumbing: `get_run` exposes canonical events + opening snapshot, and the SPA
wires the real `Timeline` component into the tool registry.

Covers both event sources: generator runs carry a separate `events.jsonl`; cli run-eval runs have
their canonical envelopes directly in `trajectory.jsonl`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saasworld.openenv import create_env_app

pytestmark = pytest.mark.openenv


def _write(d: Path, name: str, rows: list[dict]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("".join(json.dumps(r) + "\n" for r in rows))


def _agent_run(base: Path) -> None:
    d = base / "agent-run"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({"kind": "agent"}))
    _write(d, "trajectory.jsonl", [{"turn": 0, "verb": "send_message", "args": {}}])
    _write(d, "events.jsonl", [
        {"seq": 0, "sim_time": "D1T09:00", "actor": "agent", "kind": "send_message",
         "payload": {}, "delta": [{"op": "append", "path": "messages", "value": {"id": "m1"}}],
         "caused_by": None},
        {"seq": 1, "sim_time": "D1T09:05", "actor": "org.cto", "kind": "message_received",
         "payload": {}, "delta": None, "caused_by": 0},
    ])
    (d / "snapshots").mkdir(exist_ok=True)
    (d / "snapshots" / "0.json").write_text(
        json.dumps({"seq": 0, "sim_time": "D1T09:00", "state": {"messages": []}}))


def _cli_run(base: Path) -> None:
    d = base / "cli-run"
    _write(d, "trajectory.jsonl", [
        {"seq": 0, "sim_time": "D1T09:00", "actor": "agent", "kind": "send_message",
         "payload": {}, "delta": None, "caused_by": None},
        {"seq": 1, "sim_time": "D1T09:05", "actor": "org.cto", "kind": "message_received",
         "payload": {}, "delta": None, "caused_by": 0},
    ])


def test_get_run_exposes_canonical_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAASWORLD_RUNS_DIR", str(tmp_path))
    _agent_run(tmp_path)
    _cli_run(tmp_path)
    client = TestClient(create_env_app())

    agent = client.get("/inspector/api/runs/agent-run").json()
    assert agent["has_events"] is True
    assert len(agent["events"]) >= 2
    assert agent["opening"] is not None and agent["opening"]["state"] == {"messages": []}
    assert any(e["delta"] for e in agent["events"])
    assert any(e["caused_by"] == 0 for e in agent["events"])

    cli = client.get("/inspector/api/runs/cli-run").json()
    assert cli["kind"] == "cli"
    assert cli["has_events"] is True
    assert len(cli["events"]) == 2  # derived from trajectory.jsonl (no events.jsonl)
    assert cli["opening"] is None


def test_spa_wires_real_timeline() -> None:
    client = TestClient(create_env_app())
    page = client.get("/inspector").text
    assert "const Timeline = ({ run })" in page
    assert "View: Timeline" in page
    assert "TimelinePlaceholder" not in page
