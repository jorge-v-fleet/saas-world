"""Build-time verbs route to the (faked) engine seam and shape the envelope + exit codes."""

from __future__ import annotations

import pytest

from saasworld import engine

from .conftest import Harness

pytestmark = pytest.mark.cli


def test_generate_returns_summary_and_path(cli: Harness, fake_engine: None) -> None:
    env = cli.json("generate", "hidden-critical-blocker", "--seed", "7", "--out", "gen-7")
    assert env["ok"] is True and env["command"] == "generate"
    assert env["data"]["seed"] == 7
    assert env["data"]["summary"] == {"facts": 3}


def test_validate_pass(cli: Harness, fake_engine: None) -> None:
    env = cli.json("validate", "gen-7")
    assert env["ok"] is True
    assert env["data"]["passed"] is True


def test_validate_reject_is_integrity_exit_3(
    cli: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        engine, "validate",
        lambda d: engine.Verdict(False, True, False, True, "solvable-floor failed"),
    )
    result = cli.invoke("validate", "gen-7", "--json")
    assert result.exit_code == 3
    assert '"ok":false' in result.stdout and '"code":"integrity"' in result.stdout


def test_freeze_returns_hash(cli: Harness, fake_engine: None) -> None:
    env = cli.json("freeze", "gen-7")
    assert env["data"]["instance_hash"] == "sha256:deadbeef"
    assert env["data"]["provenance"]["seed"] == 7
