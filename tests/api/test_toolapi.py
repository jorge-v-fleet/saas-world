"""Tool API unit tests (drive the app via in-process TestClient).

Full checklist:
- envelope validation: unknown verb (-32601), bad/missing args (-32602), precondition (1001),
  denied write (1002)
- clock-class routing: observe emits no event; mutate is zero-duration; advance releases the clock
- observation shape: {ok, sim_time, ack, events_since}
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.toolapi


def test_health(client: object) -> None:
    r = client.get("/health")  # type: ignore[attr-defined]
    assert r.status_code == 200


def test_unknown_verb_returns_rpc_error(client: object) -> None:
    r = client.post(  # type: ignore[attr-defined]
        "/rpc",
        json={"jsonrpc": "2.0", "id": 1, "method": "action",
              "params": {"verb": "nope", "args": {}}},
    )
    assert r.json()["error"]["code"] == -32601
