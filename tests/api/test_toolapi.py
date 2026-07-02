"""Tool API: request validation and error mapping."""

import pytest

pytestmark = pytest.mark.toolapi


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_unknown_verb_returns_rpc_error(client):
    r = client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": 1, "method": "action",
              "params": {"verb": "nope", "args": {}}},
    )
    assert r.json()["error"]["code"] == -32601
