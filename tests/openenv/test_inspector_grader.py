"""Grader fact-view (POV): the run detail exposes the full `score` decomposition, and the SPA
wires the real `GraderView` (Σ weight×credit derivation, checkpoint grouping, reason parsing,
state-grounded marker) into the tool registry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saasworld.openenv import create_env_app

pytestmark = pytest.mark.openenv


def _agent_run_with_score(base: Path) -> None:
    d = base / "graded-run"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({"kind": "agent"}))
    (d / "trajectory.jsonl").write_text(
        json.dumps({"turn": 0, "verb": "send_message", "args": {}}) + "\n"
    )
    score = {
        "final": 0.7,
        "weights_sum": 1.0,
        "checkpoints": [
            {
                "checkpoint_id": "cp.midweek",
                "at": 1020,
                "subtotal": 0.7,
                "predicates": [
                    {  # pass, reads real state
                        "id": "blocker.surfaced",
                        "weight": 0.4,
                        "credit": 1.0,
                        "weighted": 0.4,
                        "status": "pass",
                        "reason": "blockers.blocker.psp_cert.surfaced == True",
                        "reads_real_field": True,
                    },
                    {  # fail, set-membership reason
                        "id": "owner.assigned",
                        "weight": 0.3,
                        "credit": 0.0,
                        "weighted": 0.0,
                        "status": "fail",
                        "reason": "projects.proj.owner=['none'] not in ['org.cto']",
                        "reads_real_field": True,
                    },
                    {  # pass, but not grounded in real state
                        "id": "note.written",
                        "weight": 0.3,
                        "credit": 1.0,
                        "weighted": 0.3,
                        "status": "pass",
                        "reason": "notes[?about=='launch'] matched 2",
                        "reads_real_field": False,
                    },
                ],
            }
        ],
        "artifact_results": [
            {
                "id": "decision.launch",
                "weight": 0.0,
                "credit": 0.0,
                "weighted": 0.0,
                "status": "pending",
                "reason": "no structured record_decision; free-text deferred to extractor",
                "reads_real_field": True,
            }
        ],
    }
    (d / "score.json").write_text(json.dumps(score))


def test_get_run_exposes_full_score_decomposition(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAASWORLD_RUNS_DIR", str(tmp_path))
    _agent_run_with_score(tmp_path)
    detail = TestClient(create_env_app()).get("/inspector/api/runs/graded-run").json()

    score = detail["score"]
    assert score is not None
    assert score["final"] == 0.7 and score["weights_sum"] == 1.0
    cp = score["checkpoints"][0]
    assert cp["checkpoint_id"] == "cp.midweek" and cp["subtotal"] == 0.7
    assert {p["status"] for p in cp["predicates"]} == {"pass", "fail"}
    assert any(p["reads_real_field"] is False for p in cp["predicates"])
    assert score["artifact_results"][0]["status"] == "pending"


def test_spa_wires_real_grader() -> None:
    page = TestClient(create_env_app()).get("/inspector").text
    assert "const GraderView" in page
    assert "View: GraderView" in page
    assert "GraderPlaceholder" not in page
