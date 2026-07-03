"""`build_set` fans a template out into N valid frozen instances + a reproducible manifest.

Walks seeds in order, skips gate rejects, materializes each valid instance, and records exactly
which seeds back the set. Deterministic: same (substrate, template, start) -> same seed list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saasworld.engine import build_set
from saasworld.engine.gate import clear_cache, gate_once
from saasworld.engine.substrate import load_substrate, load_template
from saasworld.kernel import Kernel
from saasworld.scenario.loader import load as load_scenario
from saasworld.state.store import WorldState

pytestmark = pytest.mark.integration

ARCHETYPE = "delivery-slip"


def test_materializes_exactly_count_valid_instances(tmp_path: Path) -> None:
    r = build_set(ARCHETYPE, count=5, start=0, out_root=tmp_path)
    assert len(r.seeds) == 5
    # every materialized dir exists, is frozen, and loads through the real loader
    for name in r.dirs:
        d = tmp_path / name
        assert json.loads((d / "scenario.json").read_text())["frozen"] is True
        load_scenario(str(d), Kernel(WorldState()))


def test_skips_gate_rejects_and_only_keeps_valid(tmp_path: Path) -> None:
    r = build_set(ARCHETYPE, count=5, start=0, out_root=tmp_path)
    tpl, sub = load_template(ARCHETYPE), load_substrate()
    # each recorded seed truly passes the gate ...
    for seed in r.seeds:
        clear_cache()
        assert gate_once(tpl, seed, sub)[0].passed
    # ... and the run skipped at least one reject (delivery-slip mis-binds critical_project by RNG)
    assert r.rejected >= 1
    assert r.seeds == sorted(r.seeds)  # emitted in seed order


def test_manifest_is_written_and_reproducible(tmp_path: Path) -> None:
    r1 = build_set(ARCHETYPE, count=4, start=0, out_root=tmp_path)
    manifest = json.loads(Path(r1.manifest_path).read_text())
    assert manifest["archetype"] == ARCHETYPE
    assert manifest["seeds"] == r1.seeds
    assert [m["seed"] for m in manifest["members"]] == r1.seeds
    # same inputs -> identical seed list (deterministic fan-out)
    r2 = build_set(ARCHETYPE, count=4, start=0, out_root=tmp_path / "again")
    assert r2.seeds == r1.seeds


def test_reuses_an_existing_instance_dir_instead_of_duplicating(tmp_path: Path) -> None:
    # A pre-existing instance for a seed the set will hit is reused by name, not re-materialized.
    r_probe = build_set(ARCHETYPE, count=3, start=0, out_root=tmp_path)
    reused_seed = r_probe.seeds[1]
    curated = tmp_path / "curated-name"
    (tmp_path / f"{ARCHETYPE}-{reused_seed}").rename(curated)

    r = build_set(ARCHETYPE, count=3, start=0, out_root=tmp_path)
    hit = next(m for m in json.loads(Path(r.manifest_path).read_text())["members"]
               if m["seed"] == reused_seed)
    assert hit["dir"] == "curated-name"
    assert not (tmp_path / f"{ARCHETYPE}-{reused_seed}").exists()
