"""traj ls / show / replay / query render from the driven run and derived index (read-only)."""

from __future__ import annotations

import pytest

from .conftest import SCENARIO, Harness

pytestmark = pytest.mark.observability

_DECISION = ('{"about":"proj.checkout","type":"gonogo","action":"reschedule",'
             '"new_date":"D8T17:00","owner":"org.be_b2"}')


def _driven(cli: Harness) -> str:
    run = str(cli.json("load", SCENARIO)["run_id"])
    cli.json("step", "--run", run, "--verb", "record_decision", "--args", _DECISION)
    cli.json("advance", "--run", run, "--by", "600")
    cli.json("run-eval", "--run", run)
    return run


def test_ls_lists_the_run(cli: Harness) -> None:
    run = _driven(cli)
    rows = cli.json("traj", "ls")["data"]
    assert any(r["run_id"] == run and r["total"] > 0 for r in rows)


def test_ls_filters_by_scenario(cli: Harness) -> None:
    _driven(cli)
    assert cli.json("traj", "ls", "--scenario", "no-such")["data"] == []


def test_show_returns_causal_log(cli: Harness) -> None:
    run = _driven(cli)
    rows = cli.json("traj", "show", run)["data"]
    kinds = [r["kind"] for r in rows]
    assert "record_decision" in kinds
    assert all({"seq", "sim_time", "actor", "kind", "payload", "delta", "caused_by"} <= set(r)
               for r in rows)


def test_show_seq_range(cli: Harness) -> None:
    run = _driven(cli)
    rows = cli.json("traj", "show", run, "--from", "4", "--to", "4")["data"]
    assert all(r["seq"] == 4 for r in rows)


def test_replay_is_byte_exact_zero_model_calls(cli: Harness) -> None:
    run = _driven(cli)
    env = cli.json("traj", "replay", run)
    assert env["data"]["model_calls"] == 0
    assert len(env["data"]["final_state_hash"]) == 64


def test_query_sql_escape_hatch(cli: Harness) -> None:
    run = _driven(cli)
    rows = cli.json("traj", "query", "--sql", "SELECT run_id, total FROM runs")["data"]
    assert any(r["run_id"] == run for r in rows)


def test_query_reward_hack_flags_activity_without_outcomes(cli: Harness) -> None:
    """A run of pure messaging (no graded delta) is flagged; a real decision is not."""
    run = str(cli.json("load", SCENARIO)["run_id"])
    for i in range(4):
        cli.json("step", "--run", run, "--verb", "send_message",
                 "--args", f'{{"to":"chan.checkout","body":"ping {i}"}}')
    cli.json("run-eval", "--run", run)
    flagged = cli.json("traj", "query", "--reward-hack")["data"]
    assert any(r["run_id"] == run for r in flagged)


def test_query_requires_a_preset(cli: Harness) -> None:
    _driven(cli)
    assert cli.invoke("traj", "query", "--json").exit_code == 2
