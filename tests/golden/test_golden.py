"""Flagship determinism test: fixed action script + fixed seed -> byte-identical event log + snapshot.

Implement:
- a run_script(actions) helper that drives create_app() via TestClient with a fixed action list,
  then captures (canonical event log, final snapshot)
- compare to the stored golden; with --update-golden, rewrite it instead
- run twice in-process and assert both runs are identical (replay-grade determinism)
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).parent / "core_loop.json"


@pytest.mark.skip(reason="Wave 1: implement run_script + generate golden")
def test_core_loop_matches_golden(update_golden: bool) -> None: ...
