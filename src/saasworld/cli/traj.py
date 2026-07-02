"""Observability verbs: traj ls / show / replay / pov / query.

Pure reads over the canonical JSONL log and the rebuildable DuckDB index — no writes, no second
record. ``replay`` reconstructs byte-exactly with zero model calls; ``pov`` projects the log through
an actor's scope; ``query`` runs the named cross-trajectory analyses.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from saasworld.trajectory.index import TrajectoryIndex
from saasworld.trajectory.project import project
from saasworld.trajectory.replay import read_records, replay
from saasworld.trajectory.store import canonical

from . import backend
from .render import CliError, Payload

# Partitions the agent can observe; the hidden-blocker mechanism is deliberately out of scope.
_AGENT_PATHS = ["org", "projects", "tasks", "chat", "email", "calendar", "docs", "messages",
                "decisions", "surfaces"]


def _index() -> TrajectoryIndex:
    idx = TrajectoryIndex(backend.index_path())
    idx.rebuild(backend.runs_dir())
    return idx


def ls(scenario: str | None, agent_version: str | None) -> Payload:
    idx = _index()
    cols = "run_id, scenario_id, seed, agent_version, total, n_actions"
    rows = idx.sql(f"SELECT {cols} FROM runs ORDER BY run_id")
    idx.close()
    if scenario is not None:
        rows = [r for r in rows if r["scenario_id"] == scenario]
    if agent_version is not None:
        rows = [r for r in rows if r["agent_version"] == agent_version]
    return Payload(rows)


def show(run_id: str, frm: int | None, to: int | None) -> Payload:
    records = _records(run_id)
    out = [
        {"seq": r["seq"], "sim_time": r["sim_time"], "actor": r["actor"], "kind": r["kind"],
         "payload": r["payload"], "delta": r["delta"], "caused_by": r["caused_by"]}
        for r in records
        if (frm is None or r["seq"] >= frm) and (to is None or r["seq"] <= to)
    ]
    return Payload(out, run_id=run_id)


def replay_run(run_id: str) -> Payload:
    """Reconstruct the episode and assert byte-exactness vs. the on-disk log + final snapshot."""
    rd = backend.runs_dir() / run_id
    raw = (rd / "trajectory.jsonl").read_text() if (rd / "trajectory.jsonl").exists() else ""
    if not raw:
        raise CliError("runtime", f"no trajectory for run {run_id!r}")
    result = replay(run_id, backend.runs_dir())
    if result.event_log != raw:
        raise CliError("integrity", f"replay diverged from the log for {run_id!r}")
    final = _final_snapshot(rd)
    if final is not None and result.final_state != final:
        raise CliError("integrity", f"replay final state diverged from the snapshot for {run_id!r}")
    digest = hashlib.sha256(canonical(result.final_state).encode()).hexdigest()
    return Payload({"model_calls": result.model_calls, "records": len(result.records),
                    "final_state_hash": digest}, run_id=run_id)


def pov(run_id: str, actor: str, at: int, npc: str | None) -> Payload:
    scopes = _scopes(run_id, npc)
    view = project(run_id, actor, at, scopes=scopes, base_dir=backend.runs_dir())
    return Payload({"actor": view.actor, "at": view.at, "seq": view.seq, "state": view.state,
                    "events": view.events, "extras": view.extras}, run_id=run_id, sim_time=at)


def query(regression: bool, instance_hash: str | None, failure_clusters: bool,
          reward_hack: bool, sql: str | None) -> Payload:
    idx = _index()
    try:
        if regression:
            if not instance_hash:
                raise CliError("usage", "--regression requires --instance-hash")
            data: Any = idx.regression(instance_hash)
        elif failure_clusters:
            data = idx.failure_clusters()
        elif reward_hack:
            data = idx.reward_hack()
        elif sql is not None:
            data = idx.sql(sql)
        else:
            raise CliError("usage", "traj query needs a preset (--regression/--failure-clusters/"
                                    "--reward-hack) or --sql")
    finally:
        idx.close()
    return Payload(data)


# ---- helpers --------------------------------------------------------------------------------

def _records(run_id: str) -> list[dict[str, Any]]:
    if not (backend.runs_dir() / run_id / "manifest.json").exists():
        raise CliError("runtime", f"unknown run {run_id!r}")
    return read_records(run_id, backend.runs_dir())


def _final_snapshot(rd: Path) -> dict[str, Any] | None:
    snaps = sorted((rd / "snapshots").glob("*.json"), key=lambda p: int(p.stem))
    return json.loads(snaps[-1].read_text())["state"] if snaps else None


def _scopes(run_id: str, npc: str | None) -> dict[str, dict[str, list[str]]]:
    """Per-actor scopes: agent (visible partitions), grader (eval fact-view), npc (its traffic)."""
    scopes: dict[str, dict[str, list[str]]] = {
        "agent": {"paths": _AGENT_PATHS, "actors": ["agent"]},
        "grader": {"paths": _grader_paths(run_id), "actors": ["evaluator"]},
    }
    if npc is not None:
        scopes["npc"] = {"paths": ["messages", "chat"], "actors": [npc]}
    return scopes


def _grader_paths(run_id: str) -> list[str]:
    """Roots of every path the eval predicates read — the exact fact-view the grader sees."""
    rd = backend.runs_dir() / run_id
    manifest = json.loads((rd / "manifest.json").read_text())
    from saasworld.scenario.loader import _resolve

    eval_path = _resolve(manifest["instance"]) / "eval.json"
    if not eval_path.exists():
        return []
    roots: set[str] = set()
    _collect_paths(json.loads(eval_path.read_text()), roots)
    return sorted(roots)


def _collect_paths(node: Any, roots: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("path", "exists") and isinstance(value, str):
                roots.add(value.split(".", 1)[0].split("[", 1)[0])
            else:
                _collect_paths(value, roots)
    elif isinstance(node, list):
        for item in node:
            _collect_paths(item, roots)
