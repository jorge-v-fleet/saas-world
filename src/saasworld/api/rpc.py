"""JSON-RPC 2.0 dispatch + error mapping for the Tool API.

Methods: action({verb,args}) · observe({actor}) · get_state({path}) · now() ·
         load_bootstrap({name}) · snapshot() · restore({snap}).

action() routes by the verb's clock class:
  observe -> scoped view, no event
  mutate  -> schedule(now, ...) + apply, return ack + events since last observation
  advance -> advance_until(now + duration), return all fired events, time-ordered
"""

from __future__ import annotations

from typing import Any

# JSON-RPC standard + custom error codes
ERR_UNKNOWN_METHOD = -32601
ERR_INVALID_PARAMS = -32602
ERR_PRECONDITION = 1001
ERR_DENIED_WRITE = 1002


def dispatch(
    kernel: Any, state: Any, catalog: dict[str, Any], method: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Route a JSON-RPC method; return a JSON-RPC result object ({"result": ...} or {"error": ...})."""
    raise NotImplementedError
