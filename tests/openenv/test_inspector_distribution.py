"""Distribution (cohort stats): the /api/cohort endpoint aggregates a folder of runs into
reward stats, per-archetype means±CI, checkpoint pass-rates + heatmap, and a reward-hack scatter;
the SPA wires the real DistributionView into the tool registry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saasworld.openenv import create_env_app

pytestmark = pytest.mark.openenv


def _score(p1_pass: bool, p2_pass: bool) -> dict:
    def pred(pid: str, ok: bool) -> dict:
        return {"id": pid, "weight": 0.5, "credit": 1.0 if ok else 0.0,
                "weighted": 0.5 if ok else 0.0, "status": "pass" if ok else "fail",
                "reason": "x", "reads_real_field": True}
    return {"final": (0.5 if p1_pass else 0.0) + (0.5 if p2_pass else 0.0),
            "weights_sum": 1.0,
            "checkpoints": [{"checkpoint_id": "cp", "at": 100, "subtotal": 0.0,
                             "predicates": [pred("a.done", p1_pass), pred("b.done", p2_pass)]}],
            "artifact_results": []}


def _run(base: Path, name: str, *, archetype: str, reward: float, msgs: int,
         p1: bool, p2: bool, events: list | None) -> None:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(
        {"kind": "random", "scenario": archetype, "archetype": archetype,
         "final_reward": reward, "actions": msgs + 1}))
    rows = [{"turn": 0, "verb": "wait", "args": {}, "error": None}]
    for i in range(msgs):
        rows.append({"turn": i + 1, "verb": "send_message", "args": {}, "error": None})
    (d / "trajectory.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (d / "score.json").write_text(json.dumps(_score(p1, p2)))
    if events is not None:
        (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _cohort(base: Path) -> None:
    roll = base / "rollouts"
    ev_real = [{"seq": 1, "actor": "agent", "kind": "update_doc",
                "delta": [{"op": "append", "path": "docs", "value": {}}], "caused_by": None},
               {"seq": 2, "actor": "system", "kind": "tick", "delta": None, "caused_by": None}]
    _run(roll, "r1-delivery", archetype="delivery-slip", reward=0.9, msgs=2,
         p1=True, p2=True, events=ev_real)
    _run(roll, "r2-delivery", archetype="delivery-slip", reward=0.2, msgs=5,
         p1=True, p2=False, events=[{"seq": 1, "actor": "system", "kind": "tick",
                                     "delta": None, "caused_by": None}])
    _run(roll, "r3-triage", archetype="release-triage", reward=0.6, msgs=1,
         p1=False, p2=True, events=None)  # no events.jsonl -> fallback to mutate-ish actions
    _run(roll, "r4-triage", archetype="release-triage", reward=0.1, msgs=8,
         p1=False, p2=False, events=None)
    # a root-level run (folder "(root)")
    _run(base, "root-run", archetype="delivery-slip", reward=0.5, msgs=0,
         p1=True, p2=True, events=None)


def test_cohort_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAASWORLD_RUNS_DIR", str(tmp_path))
    _cohort(tmp_path)
    c = TestClient(create_env_app())

    d = c.get("/inspector/api/cohort?folder=rollouts").json()
    assert d["n"] == 4 and d["folder"] == "rollouts"
    assert len(d["rewards"]) == 4
    assert d["mean"] is not None and d["ci_low"] is not None and d["ci_high"] is not None
    assert d["ci_low"] <= d["mean"] <= d["ci_high"]
    assert len(d["reward_hist"]) == 10 and sum(d["reward_hist"]) == 4

    arch = {r["archetype"]: r for r in d["per_archetype"]}
    assert set(arch) == {"delivery-slip", "release-triage"}
    assert arch["delivery-slip"]["n"] == 2
    assert arch["delivery-slip"]["reward_ci_low"] is not None

    per_id = {p["id"]: p for p in d["checkpoints"]["per_id"]}
    assert per_id["a.done"]["n"] == 4 and per_id["a.done"]["pass"] == 2
    assert per_id["a.done"]["pass_rate"] == 0.5
    heat = {h["run_id"]: h["results"] for h in d["checkpoints"]["heatmap"]}
    assert len(heat) == 4
    assert set(next(iter(heat.values()))) == {"a.done", "b.done"}

    scat = {s["run_id"].split("/")[-1]: s for s in d["scatter"]}
    assert scat["r2-delivery"]["n_messages"] == 5
    assert scat["r1-delivery"]["n_real_deltas"] == 1     # one non-null delta in events.jsonl
    assert scat["r2-delivery"]["n_real_deltas"] == 0     # only a null-delta tick event
    assert scat["r3-triage"]["n_real_deltas"] == 1       # fallback: 1 send_message, no reads
    assert scat["r1-delivery"]["reward"] == 0.9

    root = c.get("/inspector/api/cohort?folder=(root)").json()
    assert root["n"] == 1 and root["scatter"][0]["run_id"] == "root-run"


def test_cohort_empty_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAASWORLD_RUNS_DIR", str(tmp_path))
    d = TestClient(create_env_app()).get("/inspector/api/cohort?folder=nope").json()
    assert d["n"] == 0 and d["rewards"] == [] and d["per_archetype"] == []


def test_spa_wires_real_distribution() -> None:
    page = TestClient(create_env_app()).get("/inspector").text
    assert "const DistributionView" in page
    assert "View: DistributionView" in page
    assert "DistributionPlaceholder" not in page
