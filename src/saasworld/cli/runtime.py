"""Runtime verbs: load / step / advance / observe / run-eval.

Every mutation routes through the Tool API dispatch on the Kernel's single-writer path — the CLI
never writes world state itself. Embedded (default) checkpoints the live session between one-shot
commands; HTTP forwards the same JSON-RPC calls to a running serve process.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from saasworld.api.rpc import dispatch
from saasworld.eval.score import score
from saasworld.scenario.loader import _resolve
from saasworld.trajectory.index import TrajectoryIndex
from saasworld.trajectory.replay import read_records
from saasworld.trajectory.store import canonical

from . import backend
from .render import CliError, Payload, rpc_error


def _result(reply: dict[str, Any]) -> Any:
    """Unwrap a dispatch reply, mapping a JSON-RPC error to the right CliError kind/exit code."""
    if "error" in reply:
        raise rpc_error(reply["error"]["code"], reply["error"]["message"])
    return reply["result"]


def _dispatch(session: backend.Session, method: str, params: dict[str, Any]) -> Any:
    reply = dispatch(session.kernel, session.world, session.catalog, method, params)
    return _result(reply)


# ---- load -----------------------------------------------------------------------------------

def load(instance: str, agent_version: str, be: str, url: str) -> Payload:
    if be == "http":
        result = _result(backend.http_rpc(url, "load_scenario", {"path": instance}))
        data = {"scenario": result["scenario"], "dataset_version": result["dataset_version"]}
        return Payload(data, run_id=str(result["scenario"]))
    session = backend.start_run(instance, agent_version)
    backend.checkpoint(session)
    return Payload({"scenario": session.manifest["scenario_id"],
                    "dataset_version": session.manifest["dataset_version"],
                    "agent_version": agent_version},
                   run_id=session.run_id, sim_time=session.kernel.now())


# ---- step -----------------------------------------------------------------------------------

def step(run_id: str, verb: str, args_json: str | None, be: str, url: str) -> Payload:
    args = _parse_args(args_json)
    params = {"verb": verb, "args": args}
    if be == "http":
        result = _result(backend.http_rpc(url, "action", params))
        return Payload(result, run_id=run_id, sim_time=result.get("sim_time"))
    session = backend.resume_run(run_id)
    result = _dispatch(session, "action", params)
    backend.checkpoint(session)
    return Payload(result, run_id=run_id, sim_time=session.kernel.now())


def _parse_args(args_json: str | None) -> dict[str, Any]:
    if not args_json:
        return {}
    try:
        parsed = json.loads(args_json)
    except json.JSONDecodeError as e:
        raise CliError("usage", f"--args is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise CliError("usage", "--args must be a JSON object")
    return parsed


# ---- advance --------------------------------------------------------------------------------

def advance(run_id: str, to: int | None, by: int | None, be: str, url: str) -> Payload:
    if (to is None) == (by is None):
        raise CliError("usage", "advance needs exactly one of --to / --by")
    if be == "http":
        now = int(_result(backend.http_rpc(url, "now", {})))
        duration = (to - now) if to is not None else (by or 0)
        params = {"verb": "wait", "args": {"duration": duration}}
        result = _result(backend.http_rpc(url, "action", params))
        return Payload(result, run_id=run_id, sim_time=result.get("sim_time"))
    session = backend.resume_run(run_id)
    now = session.kernel.now()
    duration = (to - now) if to is not None else (by or 0)
    if duration < 0:
        raise CliError("usage", f"--to {to} is before current sim_time {now}")
    result = _dispatch(session, "action", {"verb": "wait", "args": {"duration": duration}})
    backend.checkpoint(session)
    return Payload(result, run_id=run_id, sim_time=session.kernel.now())


# ---- observe --------------------------------------------------------------------------------

def observe(run_id: str, actor: str, path: str | None, be: str, url: str) -> Payload:
    params = {"path": path} if path else {}
    if be == "http":
        result = _result(backend.http_rpc(url, "get_state", params))
        return Payload({"actor": actor, "state": result}, run_id=run_id)
    session = backend.resume_run(run_id)
    result = _dispatch(session, "get_state", params)
    return Payload({"actor": actor, "state": result},
                   run_id=run_id, sim_time=session.kernel.now())


# ---- run-eval -------------------------------------------------------------------------------

def run_eval(run_id: str) -> Payload:
    """Score the persisted trajectory (a pure read of the log), write score.json, refresh index."""
    rd = backend.runs_dir() / run_id
    if not (rd / "manifest.json").exists():
        raise CliError("runtime", f"unknown run {run_id!r}")
    manifest = json.loads((rd / "manifest.json").read_text())
    ground_truth = _ground_truth(manifest)
    trajectory = _reconstruct(run_id, rd)

    result = score(trajectory, ground_truth)
    score_json = {
        "total": result.final,
        "weights_sum": result.weights_sum,
        "checkpoints": {cp.checkpoint_id: cp.subtotal for cp in result.checkpoints},
        "breakdown": asdict(result),
    }
    (rd / "score.json").write_text(canonical(score_json) + "\n")
    TrajectoryIndex(backend.index_path()).refresh(run_id, backend.runs_dir())
    return Payload(asdict(result), run_id=run_id)


def _ground_truth(manifest: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(manifest["instance"]) / "eval.json"
    gt: dict[str, Any] = json.loads(path.read_text())
    return gt


def _reconstruct(run_id: str, rd: Path) -> dict[str, Any]:
    """Trajectory dict for the Evaluator: the opening snapshot + each record's applied delta."""
    opening = json.loads((rd / "snapshots" / "0.json").read_text())
    events = [
        {"seq": r["seq"], "sim_time": r["sim_time"], "actor": r["actor"], "kind": r["kind"],
         "payload": {"deltas": r["delta"] or []}, "caused_by": r["caused_by"]}
        for r in read_records(run_id, backend.runs_dir())
    ]
    return {"snapshots": [opening], "events": events}
