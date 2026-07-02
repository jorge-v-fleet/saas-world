"""Shared CLI test harness: an isolated workspace, an in-process runner, and a fake engine.

Every test drives the Typer app via ``CliRunner`` (no subprocess, no port) against a per-test
``SAASWORLD_HOME`` so runs/index never leak. The Seeding Engine seam is faked (sanctioned by the
spec) so the CLI suite is fully green without a working engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from saasworld.cli.main import app

SCENARIO = "checkout-not-ready"


@dataclass
class Harness:
    runner: CliRunner
    home: Path

    def invoke(self, *args: str) -> Any:
        return self.runner.invoke(app, list(args))

    def json(self, *args: str) -> dict[str, Any]:
        """Invoke with --json and parse the envelope from the last stdout line."""
        result = self.invoke(*args, "--json")
        line = result.stdout.strip().splitlines()[-1]
        parsed: dict[str, Any] = json.loads(line)
        return parsed


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.setenv("SAASWORLD_HOME", str(tmp_path))
    monkeypatch.delenv("SAASWORLD_BACKEND", raising=False)
    monkeypatch.chdir(tmp_path)  # contain relative --out paths so tests never write into the tree
    return Harness(CliRunner(), tmp_path)


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the engine seam with deterministic stand-ins that write a minimal instance."""
    from saasworld import engine

    def generate(archetype: str, seed: int, out_dir: Any = None) -> engine.GenerateResult:
        target = Path(out_dir) if out_dir else Path("gen") / f"{archetype}-{seed}"
        target.mkdir(parents=True, exist_ok=True)
        (target / "scenario.json").write_text(json.dumps({"id": archetype, "seed": seed}))
        return engine.GenerateResult(target, archetype, seed, ["org.cto"], {"facts": 3})

    def validate(instance_dir: Any) -> engine.Verdict:
        return engine.Verdict(True, True, True, True, "")

    def freeze(instance_dir: Any) -> engine.FreezeResult:
        return engine.FreezeResult("sha256:deadbeef", {"template_id": "t", "seed": 7})

    monkeypatch.setattr(engine, "generate", generate)
    monkeypatch.setattr(engine, "validate", validate)
    monkeypatch.setattr(engine, "freeze", freeze)
