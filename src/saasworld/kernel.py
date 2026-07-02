"""Simulation Kernel — single writer + next-event loop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .clock import SimClock
from .events import Event, EventQueue
from .protocols import StateWriter

# A handler owns an event kind's effect and returns the deltas it applied.
Handler = Callable[["Kernel", Event], list[dict[str, Any]]]
# A sink observes each applied event with the deltas that were written for it.
Sink = Callable[[Event, list[dict[str, Any]]], None]


class Kernel:
    """The only path that mutates World State. Advances by next-event jumps, never wall-clock."""

    def __init__(self, state: StateWriter, t0: int = 0) -> None:
        self.clock = SimClock(t0)
        self.queue = EventQueue()
        self.state = state
        self._seq = 0
        self._handlers: dict[str, Handler] = {}
        self._sinks: list[Sink] = []

    def register(self, kind: str, handler: Handler) -> None:
        """Route events of `kind` to a custom handler instead of the default delta path."""
        self._handlers[kind] = handler

    def add_sink(self, sink: Sink) -> None:
        """Observe every applied event (e.g. to persist a trajectory). Sinks never mutate state."""
        self._sinks.append(sink)

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
        """Route to a registered handler or the default delta path; then notify sinks."""
        handler = self._handlers.get(event.kind)
        if handler is not None:
            applied = handler(self, event)
        else:
            applied = event.payload.get("deltas", [])
            if applied:
                self.state.apply(applied, source=event.actor)
            for fu in event.payload.get("follow_ups", []):
                self.schedule(
                    event.sim_time + fu["delay"],
                    fu["actor"],
                    fu["kind"],
                    fu.get("payload", {}),
                    caused_by=event.seq,
                )
        for sink in self._sinks:
            sink(event, applied)
