"""Result envelope + human/JSON rendering, plus the exit-code error type.

Every command produces one envelope ``{ok, command, run_id?, sim_time?, data, error?}`` in a stable
key order. ``--json`` prints it as one canonical line; human mode prints the same fields as text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# kind -> process exit code (0 is success, emitted directly by the command wrapper).
_EXIT = {"runtime": 1, "usage": 2, "integrity": 3}


class CliError(Exception):
    """A command failure carrying its envelope error code and process exit code."""

    def __init__(self, kind: str, msg: str) -> None:
        super().__init__(msg)
        self.kind = kind
        self.msg = msg

    @property
    def exit_code(self) -> int:
        return _EXIT[self.kind]


def rpc_error(code: int, msg: str) -> CliError:
    """Map a JSON-RPC error code to a CliError kind (bad verb/args -> usage, else runtime)."""
    kind = "usage" if code in (-32601, -32602) else "runtime"
    return CliError(kind, msg)


@dataclass
class Payload:
    """A command's success result: opaque data plus optional run/time context for the envelope."""

    data: Any
    run_id: str | None = None
    sim_time: int | None = None


def envelope(
    command: str, ok: bool, payload: Payload | None = None, error: CliError | None = None
) -> dict[str, Any]:
    """Build the envelope in fixed key order, omitting absent optional fields."""
    env: dict[str, Any] = {"ok": ok, "command": command}
    if payload is not None and payload.run_id is not None:
        env["run_id"] = payload.run_id
    if payload is not None and payload.sim_time is not None:
        env["sim_time"] = payload.sim_time
    env["data"] = payload.data if payload is not None else None
    if error is not None:
        env["error"] = {"code": error.kind, "msg": error.msg}
    return env


def render(
    command: str, ok: bool, json_mode: bool, payload: Payload | None, error: CliError | None
) -> None:
    """Print the envelope: one canonical JSON line, or a compact human rendering of the fields."""
    env = envelope(command, ok, payload, error)
    if json_mode:
        print(json.dumps(env, separators=(",", ":")))
        return
    _human(env)


def _human(env: dict[str, Any]) -> None:
    head = f"[{env['command']}] {'ok' if env['ok'] else 'error'}"
    for key in ("run_id", "sim_time"):
        if key in env:
            head += f"  {key}={env[key]}"
    print(head)
    if env.get("error"):
        print(f"  error {env['error']['code']}: {env['error']['msg']}")
    _print_data(env.get("data"))


def _print_data(data: Any, indent: str = "  ") -> None:
    if data is None:
        return
    if isinstance(data, list):
        for item in data:
            print(indent + _oneline(item))
    elif isinstance(data, dict):
        for key, value in data.items():
            print(f"{indent}{key}: {_oneline(value)}")
    else:
        print(indent + str(data))


def _oneline(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)
