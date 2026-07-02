"""JSON-RPC 2.0 dispatch + error mapping for the Tool API.

Methods: action({verb,args}) · observe({actor}) · get_state({path}) · now() ·
         load_bootstrap({name}) · snapshot() · restore({snap}).

action() routes by the verb's clock class:
  observe -> scoped read, no event
  mutate  -> zero-duration: dry-run guard, schedule(now, ...) + apply, return ack + events
  advance -> advance_until(now + duration), return all fired events, time-ordered
"""

from __future__ import annotations

from typing import Any

from saasworld.actions.effects import bind_effect
from saasworld.bootstrap import load_bootstrap
from saasworld.events import Event
from saasworld.state.guard import check_write_allowed

# JSON-RPC standard + custom error codes
ERR_UNKNOWN_METHOD = -32601
ERR_INVALID_PARAMS = -32602
ERR_PRECONDITION = 1001
ERR_DENIED_WRITE = 1002

# observe verb -> the world partition it reads.
_OBSERVE_PARTITION = {
    "read_inbox": "email",
    "read_channel": "chat",
    "get_calendar": "calendar",
    "get_tasks": "tasks",
    "read_doc": "docs",
    "get_people": "org",
    "get_transcript": "surfaces",
}

AGENT = "org.pm_a"  # the single PM under test in Wave 1


def _err(code: int, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def event_view(e: Event) -> dict[str, Any]:
    """A JSON-serializable view of an Event."""
    return {
        "seq": e.seq,
        "sim_time": e.sim_time,
        "actor": e.actor,
        "kind": e.kind,
        "caused_by": e.caused_by,
        "payload": e.payload,
    }


def _observation(
    sim_time: int, ack: Any, events: list[dict[str, Any]]
) -> dict[str, Any]:
    return {"result": {"ok": True, "sim_time": sim_time, "ack": ack, "events_since": events}}


def _validate_args(entry: dict[str, Any], args: Any) -> str | None:
    """Reject non-object args, unknown keys, or missing required. `?` = optional (key or value)."""
    if not isinstance(args, dict):
        return "args must be an object"
    schema: dict[str, Any] = entry.get("args", {})
    allowed = {k.rstrip("?") for k in schema}
    required = {
        k.rstrip("?")
        for k, v in schema.items()
        if not (k.endswith("?") or (isinstance(v, str) and v.endswith("?")))
    }
    for key in args:
        if key not in allowed:
            return f"unknown arg {key!r}"
    for key in required:
        if key not in args:
            return f"missing required arg {key!r}"
    return None


def _precondition(verb: str, args: dict[str, Any], state: Any) -> str | None:
    """Real referential guards -> 1001 when the target doesn't exist / isn't reachable."""
    if verb == "create_task":
        if args.get("project") not in (state.read("projects") or {}):
            return f"unknown project {args.get('project')!r}"
    elif verb == "update_task":
        if args.get("task") not in (state.read("tasks") or {}):
            return f"unknown task {args.get('task')!r}"
    elif verb == "send_message":
        to = args.get("to")
        chat = state.read("chat") or {}
        if to in chat and AGENT not in chat[to].get("members", []):
            return f"agent is not a member of channel {to!r}"
    return None


def _observe_ack(verb: str, args: dict[str, Any], state: Any) -> Any:
    """Scoped read for an observe action (Wave 1: the relevant partition or a keyed entry)."""
    part = state.read(_OBSERVE_PARTITION.get(verb, "")) or {}
    if not isinstance(part, dict):
        return part
    for key in ("channel", "doc", "meeting"):
        if key in args:
            return part.get(args[key])
    if verb == "get_tasks" and args.get("project"):
        return {
            tid: t
            for tid, t in part.items()
            if isinstance(t, dict) and t.get("project") == args["project"]
        }
    return part


def _action(
    kernel: Any, state: Any, catalog: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    verb = params.get("verb")
    args = params.get("args", {})
    entry = catalog.get(verb) if isinstance(verb, str) else None
    if entry is None or not isinstance(verb, str):
        return _err(ERR_UNKNOWN_METHOD, f"unknown verb {verb!r}")
    bad = _validate_args(entry, args)
    if bad:
        return _err(ERR_INVALID_PARAMS, bad)

    cls = entry["class"]
    if cls == "observe":
        return _observation(kernel.now(), _observe_ack(verb, args, state), [])

    pre = _precondition(verb, args, state)
    if pre:
        return _err(ERR_PRECONDITION, pre)

    if cls == "advance":
        duration = args["duration"]
        applied = kernel.advance_until(kernel.now() + duration)
        return _observation(kernel.now(), {"verb": verb}, [event_view(e) for e in applied])

    # mutate — zero-duration
    if verb == "create_task":
        args = {**args, "auto_id": f"t{len(state.read('tasks') or {}) + 1}"}
    deltas, follow_ups = bind_effect(entry, args, kernel.now())
    if verb == "send_message":
        # Reactive reply only for a registered NPC target; else a plain chat append (no follow-up).
        engine = getattr(kernel, "npc_engine", None)
        to = args.get("to")
        if engine is not None and engine.is_registered(to):
            follow_ups = [*follow_ups, {"delay": engine.response_delay(to), "actor": to,
                          "kind": "npc_reply",
                          "payload": {"npc": to, "body": args.get("body", ""),
                                      "args": args, "sender": AGENT}}]
    for d in deltas:  # dry-run the guard so a denied write never enters the queue
        try:
            check_write_allowed(d["path"], "agent")
        except PermissionError:
            return _err(ERR_DENIED_WRITE, f"denied write to {d['path']}")
    seq = kernel.schedule(
        kernel.now(), "agent", verb, {"deltas": deltas, "follow_ups": follow_ups}
    )
    # Zero-duration: apply without moving time, draining any same-`now` cascade (e.g. npc_react).
    applied = kernel.advance_until(kernel.now())
    while (more := kernel.advance_until(kernel.now())):
        applied = [*applied, *more]
    return _observation(
        kernel.now(), {"seq": seq, "verb": verb}, [event_view(e) for e in applied]
    )


def dispatch(
    kernel: Any, state: Any, catalog: dict[str, Any], method: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Route a JSON-RPC method; return {"result": ...} or {"error": {code, message}}."""
    params = params or {}
    if method == "action":
        return _action(kernel, state, catalog, params)
    if method == "observe":
        return {"result": {"actor": params.get("actor"), "sim_time": kernel.now(),
                           "state": state.snapshot()}}
    if method == "get_state":
        path = params.get("path")
        return {"result": state.read(path) if path else state.snapshot()}
    if method == "now":
        return {"result": kernel.now()}
    if method == "snapshot":
        return {"result": state.snapshot()}
    if method == "restore":
        state.restore(params.get("snap", {}))
        return {"result": {"ok": True}}
    if method == "load_bootstrap":
        state.restore(load_bootstrap(params.get("name", "minimal")))
        return {"result": {"ok": True, "name": params.get("name", "minimal")}}
    if method == "load_scenario":
        from saasworld.scenario.loader import load

        loaded = load(params.get("path") or params.get("name", ""), kernel)
        return {"result": {"ok": True, "scenario": loaded.scenario_id,
                           "dataset_version": loaded.dataset_version}}
    return _err(ERR_UNKNOWN_METHOD, f"unknown method {method!r}")
