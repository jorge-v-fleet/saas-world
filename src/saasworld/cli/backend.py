"""Backend selection + embedded session persistence.

Embedded (default) constructs the app in-process per one-shot command; live session state (clock,
seq counter, pending event queue) is checkpointed beside the run in ``session.json`` and restored
next command, while world state and the canonical log stay owned by the Trajectory Store. HTTP
forwards JSON-RPC to a running ``saasworld.serve`` process that holds its own world.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saasworld.actions.catalog import load_catalog
from saasworld.events import Event
from saasworld.kernel import Kernel
from saasworld.scenario.loader import ScenarioError
from saasworld.scenario.loader import load as scenario_load
from saasworld.state.store import WorldState
from saasworld.trajectory.replay import read_records, state_at
from saasworld.trajectory.store import TrajectoryStore, open_run

from .render import CliError

_ROOT = Path(__file__).resolve().parents[3]
_CATALOG_PATH = _ROOT / "data" / "actions.json"


def workspace() -> Path:
    """Root for run artifacts; overridable so tests stay isolated and portless."""
    return Path(os.environ.get("SAASWORLD_HOME", "."))


def runs_dir() -> Path:
    return workspace() / "runs"


def index_path() -> Path:
    return workspace() / "index.duckdb"


def catalog() -> dict[str, Any]:
    return load_catalog(_CATALOG_PATH)


@dataclass
class Session:
    """A live embedded episode: kernel + world + store, plus the instance it was loaded from."""

    run_id: str
    kernel: Kernel
    world: WorldState
    catalog: dict[str, Any]
    store: TrajectoryStore
    manifest: dict[str, Any]
    instance: str


def _pending(kernel: Kernel) -> list[dict[str, Any]]:
    """Serialize the not-yet-fired event queue (its only ephemeral, non-log state)."""
    return [
        {"seq": e.seq, "sim_time": e.sim_time, "actor": e.actor, "kind": e.kind,
         "payload": e.payload, "caused_by": e.caused_by}
        for _, _, e in kernel.queue._heap  # own package: heap holds (sim_time, seq, event)
    ]


def _session_path(run_id: str) -> Path:
    return runs_dir() / run_id / "session.json"


def _write_session(session: Session) -> None:
    blob = {
        "instance": session.instance,
        "now": session.kernel.now(),
        "seq": session.kernel._seq,
        "pending": _pending(session.kernel),
    }
    _session_path(session.run_id).write_text(json.dumps(blob) + "\n")


def checkpoint(session: Session) -> None:
    """Snapshot world at the last recorded seq and persist the live session for the next command."""
    session.store.snapshot(session.store.last_seq, session.kernel.now(), session.world)
    _write_session(session)


def _run_id(scenario_id: str, agent_version: str, seed: Any) -> str:
    return f"{scenario_id}.{agent_version}.{seed}"


def start_run(instance: str, agent_version: str) -> Session:
    """Load a frozen instance into a fresh embedded episode and open its Trajectory Store run."""
    world = WorldState()
    kernel = Kernel(world)
    try:
        loaded = scenario_load(instance, kernel)
    except ScenarioError as e:
        raise CliError("integrity", str(e)) from e

    meta = _scenario_meta(instance)
    seed = meta.get("provenance", {}).get("seed", meta.get("seed", 0))
    run_id = _run_id(loaded.scenario_id, agent_version, seed)
    manifest = {
        "run_id": run_id,
        "scenario_id": loaded.scenario_id,
        "scenario_archetype": meta.get("archetype"),
        "instance_hash": meta.get("instance_hash"),
        "action_space_version": meta.get("action_space_version"),
        "dataset_version": loaded.dataset_version,
        "seed": seed,
        "agent_version": agent_version,
        "sim_t0": loaded.t0,
        "started_at_seq": 0,
        "instance": str(instance),
        "llm_models": meta.get("llm_models", {}),
    }
    store = open_run(manifest, state=world, base_dir=runs_dir())
    kernel.add_sink(store.record)
    session = Session(run_id, kernel, world, catalog(), store, manifest, str(instance))
    _write_session(session)
    return session


def resume_run(run_id: str) -> Session:
    """Rebuild a live episode from disk: world from the log, queue/clock/seq from the session."""
    rd = runs_dir() / run_id
    if not (rd / "manifest.json").exists():
        raise CliError("runtime", f"unknown run {run_id!r}")
    manifest = json.loads((rd / "manifest.json").read_text())
    sess = json.loads(_session_path(run_id).read_text())

    world = state_at(run_id, sess["seq"], runs_dir())
    kernel = Kernel(world, t0=sess["now"])
    kernel._seq = sess["seq"]

    loaded = scenario_load(sess["instance"], Kernel(WorldState()))  # re-derive NPCs only
    loaded.engine.attach(kernel)
    for e in sess["pending"]:
        kernel.queue.push(Event(e["seq"], e["sim_time"], e["actor"], e["kind"],
                                e["payload"], e["caused_by"]))

    store = TrajectoryStore(rd, manifest, world)
    store._last_seq = _last_seq(run_id)
    kernel.add_sink(store.record)
    return Session(run_id, kernel, world, catalog(), store, manifest, sess["instance"])


def _last_seq(run_id: str) -> int:
    records = read_records(run_id, runs_dir())
    return int(records[-1]["seq"]) if records else 0


def _scenario_meta(instance: str) -> dict[str, Any]:
    from saasworld.scenario.loader import _resolve

    path = _resolve(instance) / "scenario.json"
    return json.loads(path.read_text()) if path.exists() else {}


def http_rpc(url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """POST one JSON-RPC call to a running serve process; return its ``result``/``error`` body."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url + "/rpc", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 - localhost operator endpoint
            reply: dict[str, Any] = json.loads(resp.read())
    except OSError as e:
        raise CliError("runtime", f"http backend unreachable at {url}: {e}") from e
    return reply
