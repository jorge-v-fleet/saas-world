"""POV projections are correct for agent / npc / operator / grader at a sim-time."""

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


def test_operator_pov_is_the_full_log(cli: Harness) -> None:
    run = _driven(cli)
    env = cli.json("traj", "pov", run, "--actor", "operator", "--at", "600")
    kinds = {e["kind"] for e in env["data"]["events"]}
    assert "record_decision" in kinds and "meeting_start" in kinds
    # operator sees full state including the hidden blocker mechanism.
    assert "blockers" in env["data"]["state"]


def test_agent_pov_excludes_out_of_scope_paths(cli: Harness) -> None:
    run = _driven(cli)
    env = cli.json("traj", "pov", run, "--actor", "agent", "--at", "600")
    state = env["data"]["state"]
    assert "blockers" not in state  # hidden mechanism is out of the agent's scope
    assert "decisions" in state     # the agent's own writes are in scope


def test_grader_pov_surfaces_eval_fact_view_and_score(cli: Harness) -> None:
    run = _driven(cli)
    env = cli.json("traj", "pov", run, "--actor", "grader", "--at", "6780")
    state = env["data"]["state"]
    # the fact-view is exactly the paths the eval predicates read.
    assert "blockers" in state and "decisions" in state
    assert env["data"]["extras"]["score"]["total"] > 0


def test_npc_pov_scopes_to_its_traffic(cli: Harness) -> None:
    run = _driven(cli)
    env = cli.json("traj", "pov", run, "--actor", "npc", "--npc", "org.be_b2", "--at", "600")
    assert set(env["data"]["state"]).issubset({"messages", "chat"})


def test_pov_is_pure_and_repeatable(cli: Harness) -> None:
    run = _driven(cli)
    a = cli.json("traj", "pov", run, "--actor", "grader", "--at", "600")
    b = cli.json("traj", "pov", run, "--actor", "grader", "--at", "600")
    assert a == b
