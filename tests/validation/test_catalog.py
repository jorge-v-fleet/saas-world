"""Action catalog: structural validation of data/actions.json."""

from pathlib import Path

import pytest

from saasworld.actions.catalog import load_catalog

pytestmark = pytest.mark.validation

CATALOG = Path(__file__).parents[2] / "data" / "actions.json"


def test_catalog_loads():
    cat = load_catalog(CATALOG)
    assert "send_message" in cat
