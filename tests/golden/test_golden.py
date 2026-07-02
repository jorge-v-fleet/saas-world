"""Determinism: a fixed action script reproduces an identical event log and snapshot."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).parent / "core_loop.json"


@pytest.mark.skip(reason="not yet implemented")
def test_core_loop_matches_golden(update_golden):
    ...
