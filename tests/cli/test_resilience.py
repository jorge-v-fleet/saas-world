"""CLI boundary maps an unexpected handler exception to a structured envelope + exit code 1."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.cli


def test_unexpected_exception_maps_to_error_envelope(cli, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("kaboom")

    monkeypatch.setattr("saasworld.cli.runtime.observe", boom)
    result = cli.invoke("observe", "--run", "x", "--json")
    assert result.exit_code == 1  # runtime kind -> exit 1, not an uncaught traceback
    env = json.loads(result.stdout.strip().splitlines()[-1])
    assert env["ok"] is False and env["error"]["code"] == "runtime"
