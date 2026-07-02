"""Bind an action's effect template + args -> concrete deltas (+ follow-up events)."""

from __future__ import annotations

from typing import Any


def bind_effect(
    entry: dict[str, Any], args: dict[str, Any], now: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (deltas, follow_up_events) for a catalog entry bound with args at sim-time `now`.

    Follow-ups are event specs (e.g. an npc_reply at now+delay); Wave 1 has no NPC, so most
    verbs return no follow-ups. `wait` yields no deltas — the clock release happens in the API.
    """
    raise NotImplementedError
