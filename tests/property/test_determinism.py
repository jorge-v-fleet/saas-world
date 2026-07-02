"""Property-based invariants (hypothesis).

Implement:
- determinism: random VALID action sequences + fixed seed -> identical event log + final state
- ordering: after advance_until(t), all applied events have sim_time <= t, ordered by (sim_time, seq)
- single-writer: state is unchanged except across an event application
- denied-path: no agent action ever changes a denied path
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.property


@pytest.mark.skip(reason="Wave 1: implement action-sequence strategy + runner")
@given(st.lists(st.sampled_from(["read_inbox", "wait"])))
def test_replay_is_deterministic(seq: list[str]) -> None: ...
