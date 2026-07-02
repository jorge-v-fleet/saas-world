"""Cache-key canonicalization: stable under reordering, sensitive to persona/version/params."""

from __future__ import annotations

import pytest

from saasworld.llm.cache import cache_key

pytestmark = pytest.mark.llm

BASE = {
    "model": "claude-sonnet-5",
    "kind": "parse_intent",
    "system": "fixed",
    "schema": {"name": "classify_intent", "input_schema": {"type": "object"}},
    "messages": [{"role": "user", "content": "<message>\nhi\n</message>"}],
    "params": {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
    "persona": {"id": "npc.be_b2", "version": "v1"},
}


def test_identical_request_same_key() -> None:
    assert cache_key(**BASE) == cache_key(**BASE)


def test_key_stable_under_key_reordering() -> None:
    reordered = dict(BASE)
    reordered["persona"] = {"version": "v1", "id": "npc.be_b2"}  # reversed insertion order
    reordered["params"] = {"output_config": {"effort": "low"}, "thinking": {"type": "disabled"}}
    assert cache_key(**reordered) == cache_key(**BASE)


def test_persona_version_bump_changes_key() -> None:
    bumped = {**BASE, "persona": {"id": "npc.be_b2", "version": "v2"}}
    assert cache_key(**bumped) != cache_key(**BASE)


def test_params_change_changes_key() -> None:
    changed = {**BASE, "params": {"thinking": {"type": "disabled"},
                                  "output_config": {"effort": "high"}}}
    assert cache_key(**changed) != cache_key(**BASE)


def test_body_change_changes_key() -> None:
    changed = {**BASE, "messages": [{"role": "user", "content": "<message>\nbye\n</message>"}]}
    assert cache_key(**changed) != cache_key(**BASE)
