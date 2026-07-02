"""Event envelope + EventQueue (ordered by (sim_time, seq))."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    seq: int
    sim_time: int
    actor: str
    kind: str
    payload: dict[str, Any]
    caused_by: int | None = None


class EventQueue:
    """Priority queue ordered by (sim_time, seq); seq breaks ties in enqueue order."""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, Event]] = []  # (sim_time, seq, event)

    def push(self, event: Event) -> None:
        heapq.heappush(self._heap, (event.sim_time, event.seq, event))

    def pop_due(self, until: int) -> list[Event]:
        """Pop every event with sim_time <= until, returned in (sim_time, seq) order."""
        due: list[Event] = []
        while self._heap and self._heap[0][0] <= until:
            due.append(heapq.heappop(self._heap)[2])
        return due

    def __len__(self) -> int:
        return len(self._heap)
