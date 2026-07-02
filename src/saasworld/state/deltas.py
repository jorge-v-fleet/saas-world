"""Delta-DSL — the only vocabulary for state mutation."""

from __future__ import annotations

from typing import Any

OPS = ("set", "append", "inc", "link", "unlink")


def apply_delta(data: dict[str, Any], delta: dict[str, Any]) -> None:
    """Apply one {op, path, value?} op to `data` in place. Raise on unknown op / bad path."""
    raise NotImplementedError
