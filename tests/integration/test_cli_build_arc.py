"""Build arc (generate -> validate -> freeze) driven end-to-end through the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from saasworld.cli.main import app

pytestmark = pytest.mark.integration


def test_generate_validate_freeze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAASWORLD_HOME", str(tmp_path))
    runner = CliRunner()
    out = tmp_path / "gen-7"

    def js(*args: str) -> dict:
        result = runner.invoke(app, [*args, "--json"])
        assert result.exit_code == 0, result.stdout
        return json.loads(result.stdout.strip().splitlines()[-1])

    gen = js("generate", "hidden-critical-blocker", "--seed", "7", "--out", str(out))
    assert gen["data"]["seed"] == 7
    assert js("validate", str(out))["data"]["passed"] is True
    assert js("freeze", str(out))["data"]["instance_hash"]
