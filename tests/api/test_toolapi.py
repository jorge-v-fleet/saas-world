"""Tool API: envelope validation, error mapping, clock-class routing, observation shape."""

import pytest

pytestmark = pytest.mark.toolapi


def _rpc(client, method, params, id=1):
    r = client.post("/rpc", json={"jsonrpc": "2.0", "id": id, "method": method, "params": params})
    return r.json()


def _action(client, verb, args, id=1):
    return _rpc(client, "action", {"verb": verb, "args": args}, id)


# --- liveness + envelope -----------------------------------------------------


def test_health(client):
    assert client.get("/health").status_code == 200


def test_envelope_has_jsonrpc_and_id(client):
    body = _action(client, "get_people", {}, id=7)
    assert body["jsonrpc"] == "2.0" and body["id"] == 7
    assert "result" in body


# --- error mapping -----------------------------------------------------------


def test_unknown_verb_returns_rpc_error(client):
    assert _action(client, "nope", {})["error"]["code"] == -32601


def test_unknown_method_returns_rpc_error(client):
    assert _rpc(client, "bogus", {})["error"]["code"] == -32601


def test_unknown_arg_key_is_invalid_params(client):
    body = _action(client, "create_task", {"project": "proj.checkout", "title": "x", "bogus": 1})
    assert body["error"]["code"] == -32602


def test_missing_required_arg_is_invalid_params(client):
    body = _action(client, "create_task", {"title": "x"})  # missing project
    assert body["error"]["code"] == -32602


def test_precondition_failure_returns_1001(client):
    args = {"project": "proj.ghost", "title": "x", "owner": "org.fe_a1"}
    assert _action(client, "create_task", args)["error"]["code"] == 1001


def test_denied_write_returns_1002_and_leaves_field_absent(client):
    body = _action(client, "update_task", {"task": "t1", "set": {"blocked_by": "x"}})
    assert body["error"]["code"] == 1002
    got = _rpc(client, "get_state", {"path": "tasks.t1.blocked_by"})
    assert got["result"] is None  # graded field never written


# --- clock-class routing -----------------------------------------------------


def test_observe_emits_no_event_and_does_not_move_clock(client):
    body = _action(client, "get_people", {})["result"]
    assert body["events_since"] == []
    assert body["sim_time"] == 0
    assert _rpc(client, "now", {})["result"] == 0
    assert _rpc(client, "get_state", {"path": "messages"})["result"] == []


def test_mutate_is_zero_duration_and_applies_event(client):
    args = {"task": "t1", "set": {"status": "in_progress"}}
    res = _action(client, "update_task", args)["result"]
    assert res["ok"] and res["ack"]["verb"] == "update_task"
    assert res["sim_time"] == 0  # clock did not move
    assert [e["sim_time"] for e in res["events_since"]] == [0]  # applied at now
    assert res["events_since"][0]["actor"] == "agent"
    assert _rpc(client, "now", {})["result"] == 0


def test_advance_releases_the_clock(client):
    res = _action(client, "wait", {"duration": 90})["result"]
    assert res["sim_time"] == 90 and res["ack"]["verb"] == "wait"
    assert _rpc(client, "now", {})["result"] == 90


# --- observation shape -------------------------------------------------------


def test_observation_shape(client):
    res = _action(client, "get_calendar", {})["result"]
    assert set(res) == {"ok", "sim_time", "ack", "events_since"}
    assert res["ok"] is True and isinstance(res["events_since"], list)


# --- unexpected-failure mapping ----------------------------------------------


def test_unexpected_handler_error_maps_to_internal_error():
    """A handler that raises unexpectedly returns a structured -32603, never an unhandled 500."""
    from saasworld.api.rpc import ERR_INTERNAL, dispatch

    class _BoomState:
        def read(self, path):
            raise RuntimeError("boom")

    res = dispatch(None, _BoomState(), {}, "get_state", {"path": "x"})
    assert "result" not in res and res["error"]["code"] == ERR_INTERNAL
