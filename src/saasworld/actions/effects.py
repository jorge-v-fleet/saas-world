"""Bind an action's effect template + args -> concrete deltas (+ follow-up events)."""

from __future__ import annotations

from typing import Any


def bind_effect(
    entry: dict[str, Any], args: dict[str, Any], now: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (deltas, follow_up_events) for a catalog entry bound with args at sim-time `now`.

    Follow-ups are event specs (e.g. a reply scheduled at now+delay). `wait` yields no deltas —
    its clock release happens in the API layer.
    """
    raise NotImplementedError
