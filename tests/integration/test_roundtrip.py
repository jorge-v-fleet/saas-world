"""End-to-end: an action flows through the Tool API, Kernel and world state."""

import pytest

pytestmark = pytest.mark.integration


def test_action_mutates_state(client):
    client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": 1, "method": "action",
              "params": {"verb": "create_task", "args": {"project": "proj.checkout", "title": "x"}}},
    )
    r = client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": 2, "method": "get_state", "params": {"path": "tasks"}},
    )
    assert r.json()["result"]
