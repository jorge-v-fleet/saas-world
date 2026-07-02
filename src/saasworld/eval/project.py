"""Project trajectory state at a sim-time: restore nearest snapshot <= at, replay deltas forward.

Mirrors ``trajectory.replay.state_at`` but over an in-memory ``{events, snapshots}`` trajectory
(the Kernel's event log + periodic snapshots) rather than a durable run directory.
"""

from __future__ import annotations

from typing import Any

from saasworld.state.store import WorldState


def _get(ev: Any, field: str) -> Any:
    """Read a field from an Event dataclass or a plain dict record."""
    return getattr(ev, field) if hasattr(ev, field) else ev[field]


def project(trajectory: dict[str, Any], at: int) -> WorldState:
    """Reconstruct world state as of sim-time `at` onto a throwaway WorldState (never mutates live).

    Restore the latest snapshot with ``sim_time <= at``, then re-apply every later event with
    ``sim_time <= at`` in (sim_time, seq) order via the delta path (source="system").
    """
    snaps = trajectory.get("snapshots", [])
    base = max(
        (s for s in snaps if s["sim_time"] <= at),
        key=lambda s: (s["sim_time"], s["seq"]),
        default=None,
    )
    world = WorldState()
    base_seq = -1
    if base is not None:
        world.restore(base["state"])
        base_seq = base["seq"]
    events = sorted(trajectory.get("events", []),
                    key=lambda e: (_get(e, "sim_time"), _get(e, "seq")))
    for ev in events:
        if _get(ev, "seq") <= base_seq or _get(ev, "sim_time") > at:
            continue
        deltas = _get(ev, "payload").get("deltas", [])
        if deltas:
            world.apply(deltas, source="system")
    return world
