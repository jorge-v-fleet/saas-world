"""Replay — reconstruct an episode from its durable log with zero model calls.

State at any ``seq`` = the nearest snapshot with ``snap.seq <= seq`` restored, then each later
record's delta applied forward. The store adds no randomness, so replay is exact: re-serializing
the parsed log reproduces byte-identical lines, and the final state matches the final snapshot.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saasworld.state.store import WorldState

from .store import canonical

# Event kinds whose output was produced by an LLM at record time. Scripted episodes have none;
# a future replay-mode client plugs in here to resolve each such record from the recorded cassette.
LLM_KINDS: frozenset[str] = frozenset()

# Resolves an LLM-touching record to its recorded output. Default forbids any call — a replay that
# needs the network is a hard error, never a live request.
LLMResolver = Callable[[dict[str, Any]], Any]


def _forbidden_llm(record: dict[str, Any]) -> Any:
    raise RuntimeError(f"replay attempted a model call for record seq={record.get('seq')}")


def _run_dir(run_id: str, base_dir: str | Path) -> Path:
    return Path(base_dir) / run_id


def read_records(run_id: str, base_dir: str | Path = "runs") -> list[dict[str, Any]]:
    """Parse ``trajectory.jsonl`` into records, in append (== kernel seq) order."""
    path = _run_dir(run_id, base_dir) / "trajectory.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _snapshots(run_id: str, base_dir: str | Path) -> list[dict[str, Any]]:
    snap_dir = _run_dir(run_id, base_dir) / "snapshots"
    if not snap_dir.exists():
        return []
    snaps = [json.loads(p.read_text()) for p in snap_dir.glob("*.json")]
    return sorted(snaps, key=lambda s: int(s["seq"]))


def state_at(run_id: str, seq: int, base_dir: str | Path = "runs") -> WorldState:
    """Restore the nearest snapshot at/below ``seq``, then replay deltas forward to ``seq``."""
    candidates = [s for s in _snapshots(run_id, base_dir) if int(s["seq"]) <= seq]
    base = max(candidates, key=lambda s: int(s["seq"]), default=None)
    world = WorldState()
    base_seq = -1
    if base is not None:
        world.restore(base["state"])
        base_seq = int(base["seq"])
    for rec in read_records(run_id, base_dir):
        if base_seq < int(rec["seq"]) <= seq and rec["delta"]:
            world.apply(rec["delta"], source=str(rec["actor"]))
    return world


@dataclass
class ReplayResult:
    """The reconstructed episode: parsed records, byte-exact log, final state, and call count."""

    records: list[dict[str, Any]]
    event_log: str
    final_state: dict[str, Any]
    model_calls: int


def replay(
    run_id: str, base_dir: str | Path = "runs", llm: LLMResolver | None = None
) -> ReplayResult:
    """Reconstruct the episode: byte-identical event log + final snapshot, zero model calls.

    Any ``LLM_KINDS`` record would resolve through ``llm`` (a replay-mode cassette client);
    with none present the resolver is never touched, so replay is trivially offline.
    """
    resolve = llm if llm is not None else _forbidden_llm
    records = read_records(run_id, base_dir)
    calls = 0
    for rec in records:
        if rec["kind"] in LLM_KINDS:
            resolve(rec)
            calls += 1
    event_log = "".join(canonical(r) + "\n" for r in records)
    last_seq = int(records[-1]["seq"]) if records else 0
    final_state = state_at(run_id, last_seq, base_dir).snapshot()
    return ReplayResult(records, event_log, final_state, calls)
