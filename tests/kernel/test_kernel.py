"""Kernel: event ordering, clock advancement, and single-writer application.

Checklist:
- queue ordering by (sim_time, seq), incl. tie-break by seq at equal sim_time
- advance_until drains every event with sim_time <= t, in order, and stops at t
- now() is monotonic / non-decreasing and starts at t0
- seq is strictly increasing across schedules
- apply routes deltas to state.apply(source=actor); noop is a valid no-op
- apply enqueues follow-ups at sim_time+delay with caused_by set to the parent seq
- apply never touches the clock (advance_until owns it)
- Kernel never reads the wall-clock (inject a spy clock; assert no OS read)
"""

import pytest

from saasworld.clock import SimClock
from saasworld.events import Event, EventQueue
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


# --- EventQueue ordering ---------------------------------------------------

def test_queue_orders_by_sim_time_then_seq():
    q = EventQueue()
    # Push out of order; equal sim_time must tie-break by seq (enqueue order).
    q.push(Event(2, 10, "a", "noop", {}))
    q.push(Event(1, 10, "a", "noop", {}))
    q.push(Event(3, 5, "a", "noop", {}))
    out = q.pop_due(100)
    assert [(e.sim_time, e.seq) for e in out] == [(5, 3), (10, 1), (10, 2)]


def test_queue_pop_due_leaves_future_events():
    q = EventQueue()
    q.push(Event(1, 5, "a", "noop", {}))
    q.push(Event(2, 50, "a", "noop", {}))
    due = q.pop_due(10)
    assert [e.seq for e in due] == [1]
    assert len(q) == 1  # the sim_time=50 event remains
    assert [e.seq for e in q.pop_due(100)] == [2]


def test_queue_pop_due_boundary_inclusive():
    q = EventQueue()
    q.push(Event(1, 10, "a", "noop", {}))
    assert [e.seq for e in q.pop_due(9)] == []  # 10 > 9, not due
    assert [e.seq for e in q.pop_due(10)] == [1]  # sim_time == until is due


# --- advance_until ---------------------------------------------------------

def test_advance_until_stops_at_t_and_leaves_later_events(fake_state):
    k = Kernel(fake_state, t0=0)
    k.schedule(10, "system", "noop", {})
    k.schedule(70, "system", "noop", {})
    applied = k.advance_until(60)
    assert [e.sim_time for e in applied] == [10]
    assert k.now() == 60
    # The sim_time=70 event was not drained.
    later = k.advance_until(80)
    assert [e.sim_time for e in later] == [70]
    assert k.now() == 80


def test_advance_until_equal_sim_time_ordered_by_seq(fake_state):
    k = Kernel(fake_state, t0=0)
    s1 = k.schedule(20, "system", "noop", {})
    s2 = k.schedule(20, "system", "noop", {})
    applied = k.advance_until(20)
    assert [e.seq for e in applied] == [s1, s2]


def test_advance_until_no_events_still_advances_clock(fake_state):
    k = Kernel(fake_state, t0=5)
    applied = k.advance_until(40)
    assert applied == []
    assert k.now() == 40


def test_advance_until_rejects_backward_time(fake_state):
    k = Kernel(fake_state, t0=50)
    with pytest.raises(ValueError):
        k.advance_until(10)


# --- now() monotonic -------------------------------------------------------

def test_now_is_monotonic_across_advances(fake_state):
    k = Kernel(fake_state, t0=0)
    seen = [k.now()]
    for t in (5, 5, 20, 100):
        k.advance_until(t)
        seen.append(k.now())
    assert seen == sorted(seen)
    assert seen == [0, 5, 5, 20, 100]


# --- seq strictly increasing ----------------------------------------------

def test_seq_strictly_increasing(fake_state):
    k = Kernel(fake_state, t0=0)
    seqs = [k.schedule(t, "system", "noop", {}) for t in (5, 1, 9, 1)]
    assert seqs == [1, 2, 3, 4]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


# --- apply: deltas / noop / follow-ups ------------------------------------

def test_apply_routes_deltas_to_state_with_actor_source(fake_state):
    k = Kernel(fake_state, t0=0)
    deltas = [{"op": "set", "path": "tasks.T1.status", "value": "done"}]
    k.schedule(10, "alice", "edit", {"deltas": deltas})
    k.advance_until(10)
    assert fake_state.applied == [(deltas, "alice")]


def test_apply_noop_records_nothing(fake_state):
    k = Kernel(fake_state, t0=0)
    k.schedule(10, "system", "noop", {})
    k.advance_until(10)
    assert fake_state.applied == []


def test_apply_enqueues_follow_ups_with_caused_by(fake_state):
    k = Kernel(fake_state, t0=0)
    parent = k.schedule(
        10,
        "system",
        "outreach",
        {"follow_ups": [{"delay": 5, "actor": "bob", "kind": "reply"}]},
    )
    k.advance_until(10)  # applies parent, enqueues follow-up at 15
    assert fake_state.applied == []  # follow-up has no deltas yet
    follow = k.advance_until(20)
    assert len(follow) == 1
    fu = follow[0]
    assert fu.sim_time == 15  # parent.sim_time + delay
    assert fu.actor == "bob" and fu.kind == "reply"
    assert fu.caused_by == parent  # links back to the parent seq


def test_apply_follow_up_defaults_empty_payload(fake_state):
    k = Kernel(fake_state, t0=0)
    k.schedule(
        0,
        "system",
        "outreach",
        {"follow_ups": [{"delay": 1, "actor": "bob", "kind": "reply"}]},
    )
    applied = k.advance_until(5)
    # parent applied, follow-up enqueued then also drained (sim_time 1 <= 5 next pass? no)
    # follow-up scheduled after pop_due, so it fires on the next advance.
    assert [e.kind for e in applied] == ["outreach"]
    follow = k.advance_until(6)
    assert follow[0].payload == {}


def test_apply_deltas_and_follow_ups_together(fake_state):
    k = Kernel(fake_state, t0=0)
    deltas = [{"op": "inc", "path": "org.count", "value": 1}]
    parent = k.schedule(
        10,
        "carol",
        "act",
        {"deltas": deltas, "follow_ups": [{"delay": 2, "actor": "d", "kind": "noop"}]},
    )
    k.advance_until(10)
    assert fake_state.applied == [(deltas, "carol")]
    follow = k.advance_until(15)
    assert follow[0].caused_by == parent and follow[0].sim_time == 12


# --- apply must not touch the clock ---------------------------------------

def test_apply_does_not_advance_clock(fake_state):
    k = Kernel(fake_state, t0=0)
    k.schedule(10, "system", "noop", {})
    ev = k.queue.pop_due(10)[0]
    k.apply(ev)  # direct apply, bypassing advance_until
    assert k.now() == 0  # clock untouched by apply


# --- no wall-clock access --------------------------------------------------

class _SpyClock(SimClock):
    """SimClock that flags any attempt to reach past sim-time for real time."""

    def __init__(self, t0: int = 0) -> None:
        super().__init__(t0)
        self.now_calls = 0

    def now(self) -> int:
        self.now_calls += 1
        return super().now()


def test_kernel_never_reads_wall_clock(fake_state, monkeypatch):
    # Detonate if the kernel reaches for the OS clock during scheduling/advancing.
    def _boom(*_a, **_k):
        raise AssertionError("wall-clock was read")

    for name in ("time", "monotonic", "perf_counter", "time_ns"):
        monkeypatch.setattr(f"time.{name}", _boom, raising=False)

    spy = _SpyClock(t0=0)
    k = Kernel(fake_state, t0=0)
    k.clock = spy  # inject the spy so we can assert sim-time is the only source
    k.schedule(10, "system", "noop", {})
    k.advance_until(10)
    assert k.now() == 10
    assert spy.now_calls > 0  # time came from the injected sim clock, not the OS
