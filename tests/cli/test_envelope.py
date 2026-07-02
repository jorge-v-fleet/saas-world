"""The --json envelope shape/key order and the four exit codes."""

from __future__ import annotations

import json

import pytest

from .conftest import SCENARIO, Harness

pytestmark = pytest.mark.cli


def test_envelope_key_order_and_fields(cli: Harness) -> None:
    result = cli.invoke("load", SCENARIO, "--json")
    line = result.stdout.strip().splitlines()[-1]
    env = json.loads(line)
    assert list(env.keys()) == ["ok", "command", "run_id", "sim_time", "data"]
    assert env["ok"] is True and env["command"] == "load"


def test_error_envelope_has_code_and_msg(cli: Harness) -> None:
    cli.invoke("load", SCENARIO)
    env = cli.json("step", "--run", "nope", "--verb", "get_people")
    assert env["ok"] is False
    assert set(env["error"]) == {"code", "msg"}


def test_exit_0_on_success(cli: Harness) -> None:
    assert cli.invoke("load", SCENARIO, "--json").exit_code == 0


def test_exit_1_runtime_unknown_run(cli: Harness) -> None:
    result = cli.invoke("observe", "--run", "ghost", "--json")
    assert result.exit_code == 1
    assert '"code":"runtime"' in result.stdout


def test_exit_2_usage_unknown_verb(cli: Harness) -> None:
    run = cli.json("load", SCENARIO)["run_id"]
    result = cli.invoke("step", "--run", run, "--verb", "bogus_verb", "--json")
    assert result.exit_code == 2
    assert '"code":"usage"' in result.stdout


def test_exit_2_usage_bad_args_json(cli: Harness) -> None:
    run = cli.json("load", SCENARIO)["run_id"]
    result = cli.invoke("step", "--run", run, "--verb", "get_people", "--args", "{bad", "--json")
    assert result.exit_code == 2


def test_exit_1_precondition_error(cli: Harness) -> None:
    run = cli.json("load", SCENARIO)["run_id"]
    # create_task requires an existing project key; a bogus one trips the referential precondition.
    result = cli.invoke("step", "--run", run, "--verb", "create_task",
                        "--args", '{"project":"ghost","title":"x","owner":"org.fe_a1"}', "--json")
    assert result.exit_code == 1
    assert '"code":"runtime"' in result.stdout


def test_human_mode_renders_same_fields(cli: Harness) -> None:
    result = cli.invoke("load", SCENARIO)
    assert result.exit_code == 0
    assert "[load] ok" in result.stdout and "run_id=" in result.stdout
