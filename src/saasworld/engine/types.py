"""Public dataclasses for the seeding engine (re-exported from the package root).

Field names and function signatures are a stable contract the operator CLI depends on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "seed-engine/1"


@dataclass
class Verdict:
    """Validity-gate outcome — a pure function of the provenance key (cached).

    `passed` is the AND of the three gates; a failing gate names itself in `reason`.
    """

    passed: bool
    coherence: bool
    solvable_floor: bool
    nontrivial_ceiling: bool
    reason: str = ""


@dataclass
class GenerateResult:
    """`generate` output — where the candidate instance was written plus a fact-map summary."""

    out_dir: Path
    archetype: str
    seed: int
    activate: list[str]
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class FreezeResult:
    """`freeze` output — the content hash and full provenance written into `scenario.json`."""

    instance_hash: str
    provenance: dict[str, Any]
