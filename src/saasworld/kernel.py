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
        raise NotImplementedError

    def schedule(
        self,
        sim_time: int,
        actor: str,
        kind: str,
        payload: dict[str, Any],
        caused_by: int | None = None,
    ) -> int:
        """Assign a monotonic seq, enqueue the event, return its seq."""
        raise NotImplementedError

    def advance_until(self, t: int) -> list[Event]:
        """Pop + apply every due event (sim_time <= t) in order; move the clock to t."""
        raise NotImplementedError

    def apply(self, event: Event) -> None:
        """Bind the event's effect -> deltas -> state.apply(source=actor); enqueue follow-ups."""
        raise NotImplementedError
