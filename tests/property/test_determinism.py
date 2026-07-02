"""Property-based invariants: determinism, event ordering, and the write guard."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.property


@pytest.mark.skip(reason="not yet implemented")
@given(st.lists(st.sampled_from(["read_inbox", "wait"])))
def test_replay_is_deterministic(seq):
    ...
