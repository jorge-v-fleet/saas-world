"""Load + validate the action catalog (data/actions.json)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

CLOCK_CLASSES = ("observe", "mutate", "advance")


def load_catalog(path: Path) -> dict[str, dict[str, Any]]:
    """Return {verb: entry}. Raise on: unknown clock class, missing args-schema/effect,
    effect path outside a valid partition, or an effect that writes a denied path."""
    raise NotImplementedError
