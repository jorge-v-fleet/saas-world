"""SimClock — integer simulated time, decoupled from wall-clock (never reads the OS clock)."""

from __future__ import annotations


class SimClock:
    """Monotonic, non-decreasing integer clock (sim-minutes from t0)."""

    def __init__(self, t0: int = 0) -> None:
        self._now = t0

    def now(self) -> int:
        return self._now

    def advance_to(self, t: int) -> None:
        """Move the clock forward to t; t must be >= now (raise otherwise)."""
        if t < self._now:
            raise ValueError(f"cannot move clock backward: {t} < {self._now}")
        self._now = t
