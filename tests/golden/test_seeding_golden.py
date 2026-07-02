"""Flagship golden: the pinned seed regenerates `checkout-not-ready` byte-for-byte.

`generate` from the template at `example_binding._seed` emits four content files whose canonical
form equals the hand-authored scenario, and the same `instance_hash`. A companion assertion pins
that `sample -> bind` reproduces the template's illustrative `example_binding` draw.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from saasworld.content_hash import canonicalize, instance_hash
from saasworld.engine import freeze, generate
from saasworld.engine.bind import bind
from saasworld.engine.sample import sample
from saasworld.engine.substrate import load_substrate, load_template

pytestmark = pytest.mark.golden

_ROOT = Path(__file__).resolve().parents[2]
_CHECKOUT = _ROOT / "data" / "scenarios" / "checkout-not-ready"
_FILES = {
    "seed.json": "seed.json",
    "personas.overlay.json": "personas.overlay.json",
    "timeline.json": "timeline.json",
    "eval.json": "eval.json",
}


def _golden_seed() -> int:
    return int(load_template("hidden-critical-blocker")["example_binding"]["_seed"])


def test_sample_bind_reproduces_example_binding() -> None:
    substrate = load_substrate()
    template = load_template("hidden-critical-blocker")
    seed = _golden_seed()
    draw = sample(template, seed, substrate.hash)
    binding = bind(template, draw, substrate, seed)
    eb = template["example_binding"]
    for slot in ("blocker.type", "discovery.hops", "reveal.gate", "deadline.movable",
                 "distractor_blockers", "stakeholder.pressure", "deadline.offset"):
        assert draw[slot] == eb[slot], slot
    assert binding.ids == {
        "blocker.holder": eb["blocker.holder"],
        "critical_project": eb["critical_project"],
        "stakeholder": eb["stakeholder"],
    }


def test_generated_files_are_byte_identical(tmp_path: Path) -> None:
    generate("hidden-critical-blocker", _golden_seed(), out_dir=tmp_path)
    for produced, authored in _FILES.items():
        got = json.loads((tmp_path / produced).read_text())
        want = json.loads((_CHECKOUT / authored).read_text())
        assert canonicalize(got) == canonicalize(want), produced


def test_instance_hash_matches_hand_authored(tmp_path: Path) -> None:
    result = generate("hidden-critical-blocker", _golden_seed(), out_dir=tmp_path)
    frozen = freeze(result.out_dir)
    authored = instance_hash({
        "seed": json.loads((_CHECKOUT / "seed.json").read_text()),
        "overlay": json.loads((_CHECKOUT / "personas.overlay.json").read_text()),
        "timeline": json.loads((_CHECKOUT / "timeline.json").read_text()),
        "eval": json.loads((_CHECKOUT / "eval.json").read_text()),
    })
    assert frozen.instance_hash == authored


def test_freeze_is_reproducible(tmp_path: Path) -> None:
    def build(dst: Path) -> dict[str, Any]:
        generate("hidden-critical-blocker", _golden_seed(), out_dir=dst)
        freeze(dst)
        return {p.name: p.read_text() for p in sorted(dst.glob("*.json"))}

    first = build(tmp_path / "a")
    second = build(tmp_path / "b")
    assert first == second  # same key -> byte-identical instance
