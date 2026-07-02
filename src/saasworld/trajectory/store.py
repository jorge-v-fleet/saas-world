"""Trajectory writer — the durable, append-only form of the canonical event log.

Attaches to the Kernel as a sink: after every applied event the Kernel hands us the event plus
the deltas it wrote, and we append one canonical-JSON line to ``trajectory.jsonl``. The store never
mutates the world — it only observes and appends. Snapshots are periodic replay checkpoints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from saasworld.events import Event


class Snapshotable(Protocol):
    """Minimal world-state surface the store needs to checkpoint (WorldState satisfies it)."""

    def snapshot(self) -> dict[str, Any]: ...


def canonical(obj: Any) -> str:
    """Byte-stable JSON: sorted keys, compact separators. Same bytes for the same value, always."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _record_envelope(
    run_id: str, event: Event, delta: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """One JSONL row: the kernel Event superset-ed with run_id + the applied delta."""
    return {
        "run_id": run_id,
        "seq": event.seq,
        "sim_time": event.sim_time,
        "actor": event.actor,
        "kind": event.kind,
        "payload": event.payload,
        "delta": delta if delta else None,
        "caused_by": event.caused_by,
    }


class TrajectoryStore:
    """Owns ``runs/<run_id>/`` (manifest, trajectory.jsonl, snapshots, score.json). Append-only."""

    def __init__(self, run_dir: Path, manifest: dict[str, Any], state: Snapshotable | None) -> None:
        self.run_dir = run_dir
        self.manifest = manifest
        self.run_id = str(manifest["run_id"])
        self._state = state
        self._t0 = int(manifest.get("sim_t0", 0))
        self._start_seq = int(manifest.get("started_at_seq", 0))
        self._last_seq = self._start_seq
        self._last_sim_time = self._t0

    @property
    def last_seq(self) -> int:
        """Seq of the most recently recorded event (the opening seq if none yet)."""
        return self._last_seq

    def record(self, event: Event, delta: list[dict[str, Any]] | None) -> None:
        """Kernel sink: append the event (+ applied delta) as one canonical line. Never rewrites."""
        line = canonical(_record_envelope(self.run_id, event, delta))
        with (self.run_dir / "trajectory.jsonl").open("a") as f:
            f.write(line + "\n")
        self._last_seq = event.seq
        self._last_sim_time = event.sim_time

    def snapshot(self, seq: int, sim_time: int, state: Snapshotable) -> None:
        """Write a replay checkpoint ``snapshots/<seq>.json`` (round-trippable snapshot)."""
        rec = {"seq": seq, "sim_time": sim_time, "state": state.snapshot()}
        (self.run_dir / "snapshots" / f"{seq}.json").write_text(canonical(rec) + "\n")

    def close_run(self, score: dict[str, Any]) -> None:
        """Final snapshot + ``score.json`` (caller-provided; also derivable from the log)."""
        if self._state is not None:
            self.snapshot(self._last_seq, self._last_sim_time, self._state)
        (self.run_dir / "score.json").write_text(canonical(score) + "\n")


def open_run(
    manifest: dict[str, Any], state: Snapshotable | None = None, base_dir: str | Path = "runs"
) -> TrajectoryStore:
    """Create ``runs/<run_id>/``, write ``manifest.json``, and checkpoint the opening state.

    ``manifest`` is recorded verbatim — hash roles (``instance_hash``/``dataset_version``),
    ``llm_models`` and ``agent_version`` are caller-provided provenance, never computed here.
    """
    run_dir = Path(base_dir) / str(manifest["run_id"])
    (run_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(canonical(manifest) + "\n")
    store = TrajectoryStore(run_dir, manifest, state)
    if state is not None:  # opening checkpoint = replay base before any event is applied
        store.snapshot(store._start_seq, store._t0, state)
    return store
