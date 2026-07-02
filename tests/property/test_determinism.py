"""Property-based invariants: determinism, event ordering, and the write guard.

Random *valid* action sequences over a SAFE alphabet (no denied writes, no precondition
failures) are driven through the Tool API. Invariants:
  - determinism: two runs of the same sequence -> identical event log + final snapshot.
  - ordering:    after an advance to target t, every applied event has sim_time <= t and the
                 returned list is sorted by (sim_time, seq).
  - single-writer / denied-path: no agent action ever sets a denied graded path, and a direct
                 write to a denied path returns 1002.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from saasworld.api.app import create_app

pytestmark = pytest.mark.property

ERR_DENIED_WRITE = 1002

# Safe valid-action alphabet — every action is accepted against the minimal bootstrap
# (existing ids, agent is a channel member, no denied paths).
_ACTIONS = st.one_of(
    st.just({"verb": "read_inbox", "args": {}}),
    st.just({"verb": "get_people", "args": {}}),
    st.integers(min_value=0, max_value=30).map(
        lambda d: {"verb": "wait", "args": {"duration": d}}
    ),
    st.just(
        {"verb": "create_task", "args": {"project": "proj.checkout", "title": "T",
                                         "owner": "org.fe_a1"}}
    ),
    st.sampled_from(["todo", "in_progress", "done"]).map(
        lambda s: {"verb": "update_task", "args": {"task": "t1", "set": {"status": s}}}
    ),
)

_SEQ = st.lists(_ACTIONS, max_size=8)


def _call(client: TestClient, action: dict[str, Any], id_: int = 1) -> dict[str, Any]:
    return client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": id_, "method": action.get("method", "action"),
              "params": action.get("params", action)},
    ).json()


def _run(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Drive actions on a fresh app; return {log, final}."""
    client = TestClient(create_app())
    log: list[dict[str, Any]] = []
    for action in actions:
        log.extend(_call(client, action)["result"]["events_since"])
    snap = client.post(
        "/rpc", json={"jsonrpc": "2.0", "id": 2, "method": "snapshot", "params": {}}
    ).json()["result"]
    return {"log": log, "final": snap}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2)


@settings(deadline=None, max_examples=50)
@given(_SEQ)
def test_replay_is_deterministic(seq: list[dict[str, Any]]) -> None:
    assert _canonical(_run(seq)) == _canonical(_run(seq))


@settings(deadline=None, max_examples=50)
@given(prefix=_SEQ, target=st.integers(min_value=0, max_value=120))
def test_advance_events_ordered_and_bounded(prefix: list[dict[str, Any]], target: int) -> None:
    client = TestClient(create_app())
    for action in prefix:
        _call(client, action)
    t = _call(client, {"verb": "wait", "args": {"duration": target}})
    events = t["result"]["events_since"]
    now = t["result"]["sim_time"]
    keys = [(e["sim_time"], e["seq"]) for e in events]
    assert all(e["sim_time"] <= now for e in events)  # nothing fires past the target
    assert keys == sorted(keys)  # (sim_time, seq) ordered


@settings(deadline=None, max_examples=50)
@given(_SEQ)
def test_agent_never_writes_denied_paths(seq: list[dict[str, Any]]) -> None:
    final = _run(seq)["final"]
    # No graded/derived field was flipped by any agent action.
    for blk in (final.get("blockers") or {}).values():
        assert blk.get("surfaced") is False
    for task in (final.get("tasks") or {}).values():
        assert "blocked_by" not in task
    for dec in final.get("decisions") or []:
        assert "correct" not in dec


def test_direct_denied_write_returns_1002() -> None:
    client = TestClient(create_app())
    resp = _call(
        client, {"verb": "update_task", "args": {"task": "t1", "set": {"blocked_by": "b1"}}}
    )
    assert resp["error"]["code"] == ERR_DENIED_WRITE
