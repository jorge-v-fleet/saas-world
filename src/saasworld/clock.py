"""SimClock — integer simulated time, decoupled from wall-clock (never reads the OS clock)."""

from __future__ import annotations


class SimClock:
    """Monotonic, non-decreasing integer clock (sim-minutes from t0)."""

    def __init__(self, t0: int = 0) -> None:
        self._now = t0

    def now(self) -> int:
        raise NotImplementedError

    def advance_to(self, t: int) -> None:
        """Move the clock forward to t; t must be >= now (raise otherwise)."""
        raise NotImplementedError
