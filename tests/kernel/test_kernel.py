"""Kernel: event ordering, clock advancement, and single-writer application."""

import pytest

from saasworld.kernel import Kernel

pytestmark = pytest.mark.kernel


def test_now_starts_at_t0(fake_state):
    k = Kernel(fake_state, t0=0)
    assert k.now() == 0


def test_advance_until_drains_in_order(fake_state):
    k = Kernel(fake_state, t0=0)
    k.schedule(30, "system", "noop", {})
    k.schedule(10, "system", "noop", {})
    applied = k.advance_until(60)
    assert [e.sim_time for e in applied] == [10, 30]
    assert k.now() == 60
