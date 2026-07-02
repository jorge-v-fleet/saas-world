"""Write a candidate instance and stamp a frozen one with content hash + provenance.

The four content files carry the whole instance; `scenario.json` is the manifest (id, activate,
time, provenance, dataset_version). `instance_hash` content-addresses the four canonical content
files, so re-running the same key writes byte-identical files and the same hash; a `_`-note edit
never changes it. Freezing marks the directory read-only.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from ..content_hash import dataset_version, instance_hash
from .assemble import FactMap
from .types import GENERATOR_VERSION, FreezeResult

CONTENT_FILES = ("seed.json", "personas.overlay.json", "timeline.json", "eval.json")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n")


def _content(root: Path) -> dict[str, Any]:
    return {
        "seed": json.loads((root / "seed.json").read_text()),
        "overlay": json.loads((root / "personas.overlay.json").read_text()),
        "timeline": json.loads((root / "timeline.json").read_text()),
        "eval": json.loads((root / "eval.json").read_text()),
    }


def _manifest(archetype: str, seed: int, factmap: FactMap, substrate_hash: str) -> dict[str, Any]:
    return {
        "id": f"{archetype}-{seed}",
        "archetype": archetype,
        "activate": factmap.activate,
        "time": {"day1_weekday": "Mon", "horizon_days": factmap.bindings["deadline_day"]},
        "provenance": {
            "template_id": archetype,
            "seed": seed,
            "substrate_hash": substrate_hash,
            "generator_version": GENERATOR_VERSION,
        },
    }


def write_candidate(
    out_dir: Path, archetype: str, seed: int, factmap: FactMap, eval_json: dict[str, Any],
    substrate_hash: str,
) -> None:
    """Emit the four content files + a candidate (unfrozen) manifest with provenance."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "seed.json", factmap.seed)
    _write_json(out_dir / "personas.overlay.json", factmap.overlay)
    _write_json(out_dir / "timeline.json", factmap.timeline)
    _write_json(out_dir / "eval.json", eval_json)
    _write_json(out_dir / "scenario.json", _manifest(archetype, seed, factmap, substrate_hash))


def freeze(instance_dir: str | Path) -> FreezeResult:
    """Content-hash + provenance-stamp an instance, mark it immutable (rewrites `scenario.json`)."""
    root = Path(instance_dir)
    manifest = json.loads((root / "scenario.json").read_text())
    content = _content(root)
    ih = instance_hash(content)
    provenance = dict(manifest.get("provenance", {}))
    provenance["instance_hash"] = ih
    manifest["provenance"] = provenance
    manifest["dataset_version"] = dataset_version(content)
    manifest["frozen"] = True
    _mark_writable(root)  # rewrite even a previously-frozen dir
    _write_json(root / "scenario.json", manifest)
    _mark_readonly(root)
    return FreezeResult(instance_hash=ih, provenance=provenance)


def _mark_readonly(root: Path) -> None:
    """Clear the write bits on the emitted files (immutability signal, not a security boundary)."""
    ro = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    for name in (*CONTENT_FILES, "scenario.json"):
        p = root / name
        if p.exists():
            os.chmod(p, ro)


def _mark_writable(root: Path) -> None:
    for name in (*CONTENT_FILES, "scenario.json"):
        p = root / name
        if p.exists():
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
