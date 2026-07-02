"""Full CLI-driven episode over the pre-frozen checkout scenario (no Seeding Engine needed).

Drives load -> step -> advance -> run-eval -> traj show/replay/pov/query entirely through the Typer
app, and asserts the pieces agree: run-eval's total equals the index total, replay is byte-exact,
and the grader POV surfaces the persisted score. The generate/validate/freeze prefix is exercised
separately (faked in -m cli; real at the engine join).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from saasworld.cli.main import app

pytestmark = pytest.mark.integration

SCENARIO = "checkout-not-ready"
_DECISION = ('{"about":"proj.checkout","type":"gonogo","action":"reschedule",'
             '"new_date":"D8T17:00","owner":"org.be_b2"}')


def _json(runner: CliRunner, *args: str) -> dict:
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_cli_drives_scores_and_inspects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAASWORLD_HOME", str(tmp_path))
    runner = CliRunner()

    run = _json(runner, "load", SCENARIO)["run_id"]
    _json(runner, "step", "--run", run, "--verb", "record_decision", "--args", _DECISION)
    _json(runner, "advance", "--run", run, "--by", "600")
    breakdown = _json(runner, "run-eval", "--run", run)["data"]

    # run-eval agrees with the derived index total.
    rows = _json(runner, "traj", "ls")["data"]
    row = next(r for r in rows if r["run_id"] == run)
    assert row["total"] == pytest.approx(breakdown["final"])
    assert breakdown["weights_sum"] == pytest.approx(1.0)

    # replay reconstructs byte-exactly with zero model calls.
    replay = _json(runner, "traj", "replay", run)["data"]
    assert replay["model_calls"] == 0

    # the canonical log carries the agent's decision.
    log = _json(runner, "traj", "show", run)["data"]
    assert any(r["kind"] == "record_decision" for r in log)

    # grader POV surfaces the persisted score derivation.
    grader = _json(runner, "traj", "pov", run, "--actor", "grader", "--at", "6780")["data"]
    assert grader["extras"]["score"]["total"] == pytest.approx(breakdown["final"])

    # cross-trajectory query finds the run.
    hit = _json(runner, "traj", "query", "--sql", f"SELECT run_id FROM runs WHERE run_id='{run}'")
    assert hit["data"] and hit["data"][0]["run_id"] == run


def test_cli_run_eval_matches_direct_evaluator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI run-eval total equals the Evaluator scoring the reconstructed trajectory."""
    monkeypatch.setenv("SAASWORLD_HOME", str(tmp_path))
    runner = CliRunner()
    from saasworld.cli import backend, runtime
    from saasworld.eval.score import score

    run = _json(runner, "load", SCENARIO)["run_id"]
    _json(runner, "step", "--run", run, "--verb", "record_decision", "--args", _DECISION)
    cli_total = _json(runner, "run-eval", "--run", run)["data"]["final"]

    rd = backend.runs_dir() / run
    manifest = json.loads((rd / "manifest.json").read_text())
    gt = runtime._ground_truth(manifest)
    trajectory = runtime._reconstruct(run, rd)
    assert score(trajectory, gt).final == pytest.approx(cli_total)
