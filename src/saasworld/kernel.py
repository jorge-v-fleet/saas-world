"""Simulation Kernel — single writer + next-event loop."""

from __future__ import annotations

from typing import Any

from .clock import SimClock
from .events import Event, EventQueue
from .protocols import StateWriter


class Kernel:
    """The only path that mutates World State. Advances by next-event jumps, never wall-clock."""

    def __init__(self, state: StateWriter, t0: int = 0) -> None:
        self.clock = SimClock(t0)
        self.queue = EventQueue()
        self.state = state
        self._seq = 0

    def now(self) -> int:
        return self.clock.now()

    def schedule(
        self,
        sim_time: int,
        actor: str,
        kind: str,
        payload: dict[str, Any],
        caused_by: int | None = None,
    ) -> int:
        """Assign a monotonic seq, enqueue the event, return its seq."""
        self._seq += 1
        self.queue.push(Event(self._seq, sim_time, actor, kind, payload, caused_by))
        return self._seq

    def advance_until(self, t: int) -> list[Event]:
        """Pop + apply every due event (sim_time <= t) in order; move the clock to t."""
        applied = self.queue.pop_due(t)
        for event in applied:
            self.apply(event)
        self.clock.advance_to(t)
        return applied

    def apply(self, event: Event) -> None:
        """Bind the event's effect -> deltas -> state.apply(source=actor); enqueue follow-ups."""
        deltas = event.payload.get("deltas", [])
        if deltas:
            self.state.apply(deltas, source=event.actor)
        for fu in event.payload.get("follow_ups", []):
            self.schedule(
                event.sim_time + fu["delay"],
                fu["actor"],
                fu["kind"],
                fu.get("payload", {}),
                caused_by=event.seq,
            )
