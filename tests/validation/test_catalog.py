"""data/actions.json catalog validation.

Full checklist:
- every entry well-formed: id, clock class in {observe,mutate,advance}, args-schema, effect
- effect paths reference valid partitions
- no effect writes a denied path (blockers.*.surfaced, tasks.*.blocked_by, decisions.*.correct)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from saasworld.actions.catalog import load_catalog

pytestmark = pytest.mark.validation

CATALOG = Path(__file__).parents[2] / "data" / "actions.json"


def test_catalog_loads() -> None:
    cat = load_catalog(CATALOG)
    assert "send_message" in cat
