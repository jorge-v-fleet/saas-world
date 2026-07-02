"""Cross-system integration tests (real Kernel + State + Tool API via TestClient).

Full checklist:
- round trip: action(create_task/send_message) -> event applied -> get_state reflects it
- clock drain: pre-schedule a future system event -> action(wait,{duration}) fires it,
  it appears in events_since, state updated, order correct
- constrained-write e2e: an action targeting a denied path -> error 1002, graded field unchanged
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_action_mutates_state(client: object) -> None:
    client.post(  # type: ignore[attr-defined]
        "/rpc",
        json={"jsonrpc": "2.0", "id": 1, "method": "action",
              "params": {"verb": "create_task", "args": {"project": "proj.checkout", "title": "x"}}},
    )
    r = client.post(  # type: ignore[attr-defined]
        "/rpc",
        json={"jsonrpc": "2.0", "id": 2, "method": "get_state", "params": {"path": "tasks"}},
    )
    assert r.json()["result"]
