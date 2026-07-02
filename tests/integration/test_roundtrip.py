"""End-to-end: actions flow through the Tool API, Kernel and world state over TestClient."""

import pytest

pytestmark = pytest.mark.integration


def _action(client, verb, args, id=1):
    params = {"verb": verb, "args": args}
    r = client.post("/rpc", json={"jsonrpc": "2.0", "id": id, "method": "action", "params": params})
    return r.json()


def _get(client, path):
    r = client.post(
        "/rpc", json={"jsonrpc": "2.0", "id": 9, "method": "get_state", "params": {"path": path}}
    )
    return r.json()["result"]


def test_round_trip_create_task_then_get_state(client):
    # bootstrap seeds exactly one task, so the injected auto_id is deterministic (t2).
    _action(client, "create_task",
            {"project": "proj.checkout", "title": "Payments API", "owner": "org.be_b2"})
    assert _get(client, "tasks.t2.title") == "Payments API"


def test_clock_drain_fires_prescheduled_system_event_in_order(client):
    kernel = client.app.state.kernel
    # A future system reveal that flips the REAL seeded blocker — only source == "system" may write.
    kernel.schedule(30, "system", "reveal",
                    {"deltas": [{"op": "set", "path": "blockers.b1.surfaced", "value": True}]})
    kernel.schedule(50, "system", "noop", {})
    res = _action(client, "wait", {"duration": 60})["result"]
    kinds = [(e["sim_time"], e["kind"]) for e in res["events_since"]]
    assert kinds == [(30, "reveal"), (50, "noop")]  # drained in (sim_time, seq) order
    assert res["sim_time"] == 60
    assert _get(client, "blockers.b1.surfaced") is True  # seeded blocker flipped in place


def test_constrained_write_e2e_denied_leaves_graded_field_unchanged(client):
    seeded = _get(client, "tasks.t1")
    body = _action(client, "update_task", {"task": "t1", "set": {"blocked_by": "b1"}})
    assert body["error"]["code"] == 1002
    assert _get(client, "tasks.t1.blocked_by") is None  # real seeded field never written
    assert _get(client, "tasks.t1") == seeded  # task untouched


def test_non_scoring_update_mutates_seeded_task_in_place(client):
    args = {"task": "t1", "set": {"status": "in_progress"}}
    assert _action(client, "update_task", args)["result"]["ok"] is True
    assert _get(client, "tasks.t1.status") == "in_progress"  # seeded task, not a phantom
