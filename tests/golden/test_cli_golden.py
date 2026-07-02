"""Golden scripted CLI session: a fixed command list at a fixed seed reproduces byte-identically.

Captures each command's --json envelope plus the resulting trajectory.jsonl and asserts both match
the stored golden. Regenerate with ``pytest --update-golden``. Drives the pre-frozen checkout
scenario, so it needs no Seeding Engine — determinism here is the operator-surface proof.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from saasworld.cli.main import app

pytestmark = pytest.mark.golden

_GOLDEN = Path(__file__).parent / "cli_session.json"
_DECISION = ('{"about":"proj.checkout","type":"gonogo","action":"reschedule",'
             '"new_date":"D8T17:00","owner":"org.be_b2"}')
_RUN = "checkout-not-ready.baseline.0"

SESSION = [
    ["load", "checkout-not-ready"],
    ["step", "--run", _RUN, "--verb", "record_decision", "--args", _DECISION],
    ["advance", "--run", _RUN, "--by", "600"],
    ["run-eval", "--run", _RUN],
    ["traj", "show", _RUN],
    ["traj", "replay", _RUN],
    ["traj", "pov", _RUN, "--actor", "grader", "--at", "6780"],
]


def test_cli_session_is_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, update_golden: bool
) -> None:
    monkeypatch.setenv("SAASWORLD_HOME", str(tmp_path))
    runner = CliRunner()

    session: list[str] = []
    for args in SESSION:
        result = runner.invoke(app, [*args, "--json"])
        assert result.exit_code == 0, result.stdout
        session.append(result.stdout.strip().splitlines()[-1])

    trajectory = (tmp_path / "runs" / _RUN / "trajectory.jsonl").read_text().splitlines()
    captured = {"session": session, "trajectory": trajectory}

    if update_golden:
        _GOLDEN.write_text(json.dumps(captured, indent=2) + "\n")
        return

    expected = json.loads(_GOLDEN.read_text())
    assert captured == expected
