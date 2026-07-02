"""Minimal Wave-1 world seed — NOT the full Scenario Loader (no overlay/eval/dataset_version).

Provides just enough world (org/company from data/world + a few projects/tasks/channels) to
exercise the action loop. The frozen-instance loader + dataset_version validation is Wave 2.
"""

from __future__ import annotations

from typing import Any


def load_bootstrap(name: str = "minimal") -> dict[str, Any]:
    """Return an initial WorldState dict for Wave 1 dev/testing."""
    raise NotImplementedError
