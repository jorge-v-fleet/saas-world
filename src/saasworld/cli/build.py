"""Build-time verbs: generate / validate / freeze.

Thin front over the Seeding Engine's public surface — offline, no service, no episode. The CLI adds
no logic here; it parses args, calls the engine, and shapes the result into the envelope.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from saasworld import engine

from .render import CliError, Payload


def generate(archetype: str, seed: int, out: str | None) -> Payload:
    """Sample -> bind -> assemble -> project-eval into a candidate instance directory."""
    result = engine.generate(archetype, seed, out)
    return Payload({
        "out_dir": str(result.out_dir),
        "archetype": result.archetype,
        "seed": result.seed,
        "activate": result.activate,
        "summary": result.summary,
    })


def validate(instance: str) -> Payload:
    """Run the validity gate; reject (exit 3) when any sub-gate fails."""
    verdict = engine.validate(instance)
    data: dict[str, Any] = asdict(verdict)
    if not verdict.passed:
        raise CliError("integrity", f"validity gate rejected {instance}: {verdict.reason}")
    return Payload(data)


def freeze(instance: str) -> Payload:
    """Content-hash + provenance-stamp the instance and mark it immutable."""
    result = engine.freeze(instance)
    return Payload({"instance_hash": result.instance_hash, "provenance": result.provenance})
