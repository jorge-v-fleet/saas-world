"""Kernel unit tests (isolated via FakeState).

Full checklist (implement all in Wave 1):
- queue ordering by (sim_time, seq); ties broken by enqueue order
- advance_until drains every event with sim_time <= t, in order, and stops at t
- now() monotonic non-decreasing; seq strictly increasing
- apply() enqueues follow-up events; caused_by is set on follow-ups
- no OS-clock access (Kernel must not read wall-clock)
"""

from __future__ import annotations

import pytest

from saasworld.kernel import Kernel

pytestmark = pytest.mark.kernel


def test_now_starts_at_t0(fake_state: object) -> None:
    k = Kernel(fake_state, t0=0)  # type: ignore[arg-type]
    assert k.now() == 0


def test_advance_until_drains_in_order(fake_state: object) -> None:
    k = Kernel(fake_state, t0=0)  # type: ignore[arg-type]
    k.schedule(30, "system", "noop", {})
    k.schedule(10, "system", "noop", {})
    applied = k.advance_until(60)
    assert [e.sim_time for e in applied] == [10, 30]
    assert k.now() == 60
