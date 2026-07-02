"""Runtime verbs parse their args and route through the Tool API on the single-writer path."""

from __future__ import annotations

import pytest

from .conftest import SCENARIO, Harness

pytestmark = pytest.mark.cli

_DECISION = ('{"about":"proj.checkout","type":"gonogo","action":"reschedule",'
             '"new_date":"D8T17:00","owner":"org.be_b2"}')


def _load(cli: Harness) -> str:
    return str(cli.json("load", SCENARIO)["run_id"])


def test_load_prints_run_id_and_dataset_version(cli: Harness) -> None:
    env = cli.json("load", SCENARIO)
    assert env["run_id"] == "checkout-not-ready.baseline.0"
    assert env["data"]["dataset_version"].startswith("sha256:")


def test_step_mutate_returns_observation(cli: Harness) -> None:
    run = _load(cli)
    env = cli.json("step", "--run", run, "--verb", "record_decision", "--args", _DECISION)
    assert env["data"]["ack"]["verb"] == "record_decision"
    events = env["data"]["events_since"]
    assert events[0]["kind"] == "record_decision"


def test_step_observe_verb_reads_without_events(cli: Harness) -> None:
    run = _load(cli)
    env = cli.json("step", "--run", run, "--verb", "get_people")
    assert env["data"]["events_since"] == []


def test_advance_by_fires_timeline_event(cli: Harness) -> None:
    run = _load(cli)
    env = cli.json("advance", "--run", run, "--by", "600")
    assert env["sim_time"] == 600
    kinds = [e["kind"] for e in env["data"]["events_since"]]
    assert "meeting_start" in kinds


def test_advance_to_absolute_time(cli: Harness) -> None:
    run = _load(cli)
    env = cli.json("advance", "--run", run, "--to", "570")
    assert env["sim_time"] == 570


def test_advance_requires_exactly_one_bound(cli: Harness) -> None:
    run = _load(cli)
    assert cli.invoke("advance", "--run", run, "--json").exit_code == 2
    assert cli.invoke("advance", "--run", run, "--to", "1", "--by", "1", "--json").exit_code == 2


def test_session_persists_across_commands(cli: Harness) -> None:
    """A decision recorded in one invocation is visible to a later observe (checkpoint/restore)."""
    run = _load(cli)
    cli.json("step", "--run", run, "--verb", "record_decision", "--args", _DECISION)
    env = cli.json("observe", "--run", run, "--path", "decisions")
    assert env["data"]["state"][0]["about"] == "proj.checkout"


def test_run_eval_prints_weighted_breakdown(cli: Harness) -> None:
    run = _load(cli)
    cli.json("step", "--run", run, "--verb", "record_decision", "--args", _DECISION)
    env = cli.json("run-eval", "--run", run)
    assert env["data"]["weights_sum"] == pytest.approx(1.0)
    ids = {p["id"] for cp in env["data"]["checkpoints"] for p in cp["predicates"]}
    assert "acted_on_blocker" in ids
