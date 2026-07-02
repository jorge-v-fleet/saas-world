"""Backend selection resolves embedded (default) vs http, without binding a port."""

from __future__ import annotations

from typing import Any

import pytest

from saasworld.cli import backend, runtime

from .conftest import SCENARIO, Harness

pytestmark = pytest.mark.cli


def test_default_backend_is_embedded(cli: Harness) -> None:
    """No --backend and no env -> embedded, which opens a real local run directory."""
    run = cli.json("load", SCENARIO)["run_id"]
    assert (cli.home / "runs" / run / "manifest.json").exists()


def test_http_backend_forwards_rpc(monkeypatch: pytest.MonkeyPatch, cli: Harness) -> None:
    """--backend http routes through http_rpc instead of constructing an embedded session."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_http(url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((method, params))
        return {"result": {"scenario": "checkout-not-ready", "dataset_version": "sha256:x"}}

    monkeypatch.setattr(backend, "http_rpc", fake_http)
    env = cli.json("load", SCENARIO, "--backend", "http", "--url", "http://127.0.0.1:9999")
    assert env["ok"] is True
    assert calls == [("load_scenario", {"path": SCENARIO})]
    assert not (cli.home / "runs").exists()  # http keeps state server-side, no local run


def test_backend_env_var_selects_http(monkeypatch: pytest.MonkeyPatch, cli: Harness) -> None:
    monkeypatch.setenv("SAASWORLD_BACKEND", "http")
    monkeypatch.setattr(
        backend, "http_rpc",
        lambda url, method, params: {"result": {"scenario": "s", "dataset_version": "v"}},
    )
    env = cli.json("load", SCENARIO)
    assert env["ok"] is True and env["run_id"] == "s"


def test_advance_http_computes_duration_from_now(
    monkeypatch: pytest.MonkeyPatch, cli: Harness
) -> None:
    seen: list[dict[str, Any]] = []

    def fake_http(url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "now":
            return {"result": 100}
        seen.append(params)
        return {"result": {"sim_time": 160}}

    monkeypatch.setattr(backend, "http_rpc", fake_http)
    runtime.advance("run", to=160, by=None, be="http", url="http://x")
    assert seen[0]["args"]["duration"] == 60
