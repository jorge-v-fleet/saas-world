"""Derived cross-run index — a rebuildable DuckDB cache over ``runs/`` for cross-trajectory queries.

Never authoritative: one row per run derived from its manifest + trajectory + score. Drop the file
and ``rebuild`` reproduces identical rows. Ships the three named analyses (regression /
failure-clusters / reward-hack) plus a read-only ``sql`` escape hatch.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from .replay import read_records

# Delta path roots that count as real outcome changes vs. mere talk.
REAL_ROOTS = frozenset({"tasks", "projects", "blockers", "decisions", "docs", "calendar"})
MESSAGE_KINDS = frozenset({"send_message", "send_email"})

_COLUMNS = (
    "run_id VARCHAR",
    "scenario_id VARCHAR",
    "scenario_archetype VARCHAR",
    "instance_hash VARCHAR",
    "action_space_version VARCHAR",
    "dataset_version VARCHAR",
    "seed BIGINT",
    "agent_version VARCHAR",
    "total DOUBLE",
    "n_actions INTEGER",
    "n_real_deltas INTEGER",
    "n_messages INTEGER",
    "sim_duration INTEGER",
    "wall_duration DOUBLE",  # always NULL — no wall-clock is ever recorded
    "checkpoints VARCHAR",   # JSON {checkpoint: score}; parsed in Python for failure clusters
)
_FIELDS = tuple(c.split()[0] for c in _COLUMNS)


def _derive_row(run_dir: Path) -> dict[str, Any]:
    """Aggregate one index row from a run's manifest, trajectory log and score."""
    manifest = json.loads((run_dir / "manifest.json").read_text())
    score_path = run_dir / "score.json"
    score = json.loads(score_path.read_text()) if score_path.exists() else {}
    records = read_records(run_dir.name, run_dir.parent)

    n_actions = sum(1 for r in records if r["actor"] == "agent")
    n_messages = sum(1 for r in records if r["kind"] in MESSAGE_KINDS)
    n_real_deltas = sum(
        1
        for r in records
        for d in r.get("delta") or []
        if d["path"].split(".", 1)[0] in REAL_ROOTS
    )
    sim_times = [int(r["sim_time"]) for r in records]
    sim_duration = (max(sim_times) - int(manifest.get("sim_t0", 0))) if sim_times else 0

    return {
        "run_id": manifest["run_id"],
        "scenario_id": manifest.get("scenario_id"),
        "scenario_archetype": manifest.get("scenario_archetype"),
        "instance_hash": manifest.get("instance_hash"),
        "action_space_version": manifest.get("action_space_version"),
        "dataset_version": manifest.get("dataset_version"),
        "seed": manifest.get("seed"),
        "agent_version": manifest.get("agent_version"),
        "total": float(score.get("total", 0.0)),
        "n_actions": n_actions,
        "n_real_deltas": n_real_deltas,
        "n_messages": n_messages,
        "sim_duration": sim_duration,
        "wall_duration": None,
        "checkpoints": json.dumps(score.get("checkpoints", {}), sort_keys=True),
    }


class TrajectoryIndex:
    """Embedded DuckDB index; the whole DB is disposable and rebuildable from the JSONL logs."""

    def __init__(self, db_path: str | Path = "index.duckdb") -> None:
        self.conn = duckdb.connect(str(db_path))
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.conn.execute(f"CREATE TABLE IF NOT EXISTS runs ({', '.join(_COLUMNS)})")

    def _upsert(self, row: dict[str, Any]) -> None:
        self.conn.execute("DELETE FROM runs WHERE run_id = ?", [row["run_id"]])
        placeholders = ", ".join("?" for _ in _FIELDS)
        self.conn.execute(
            f"INSERT INTO runs ({', '.join(_FIELDS)}) VALUES ({placeholders})",
            [row[f] for f in _FIELDS],
        )

    def refresh(self, run_id: str, runs_dir: str | Path = "runs") -> None:
        """Re-derive and upsert a single run (incremental)."""
        self._upsert(_derive_row(Path(runs_dir) / run_id))

    def rebuild(self, runs_dir: str | Path = "runs") -> None:
        """Drop + re-derive every run under ``runs_dir``. Deterministic: sorted by run_id."""
        self.conn.execute("DELETE FROM runs")
        root = Path(runs_dir)
        for run_dir in sorted(root.iterdir()) if root.exists() else []:
            if (run_dir / "manifest.json").exists():
                self._upsert(_derive_row(run_dir))

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self.conn.execute(sql, params or [])
        cols = [d[0] for d in cur.description or []]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def regression(self, instance_hash: str) -> list[dict[str, Any]]:
        """Score trend for one comparability key across agent_version (ignores dataset edits)."""
        return self._rows(
            "SELECT instance_hash, action_space_version, agent_version, total, run_id "
            "FROM runs WHERE instance_hash = ? "
            "ORDER BY action_space_version, agent_version, run_id",
            [instance_hash],
        )

    def failure_clusters(self, threshold: float = 0.6) -> dict[str, list[str]]:
        """Group failing runs (total < threshold) by the checkpoint that scored lowest."""
        clusters: dict[str, list[str]] = {}
        for row in self._rows(
            "SELECT run_id, checkpoints FROM runs WHERE total < ? ORDER BY run_id", [threshold]
        ):
            checks: dict[str, float] = json.loads(row["checkpoints"] or "{}")
            if not checks:
                continue
            dropped = min(checks, key=lambda k: checks[k])
            clusters.setdefault(dropped, []).append(row["run_id"])
        return clusters

    def reward_hack(
        self, min_messages: int = 3, max_real_deltas: int = 0, max_total: float = 0.5
    ) -> list[dict[str, Any]]:
        """Flag activity without outcomes: many messages, ~no real deltas, low score."""
        return self._rows(
            "SELECT run_id, n_messages, n_real_deltas, total FROM runs "
            "WHERE n_messages >= ? AND n_real_deltas <= ? AND total <= ? ORDER BY run_id",
            [min_messages, max_real_deltas, max_total],
        )

    def sql(self, query: str) -> list[dict[str, Any]]:
        """Read-only escape hatch: a single SELECT over the index columns."""
        if query.lstrip().split(None, 1)[0].lower() != "select":
            raise ValueError("index.sql accepts read-only SELECT statements only")
        return self._rows(query)

    def query(self, name: str, **kwargs: Any) -> Any:
        """Dispatch a named analysis: regression / failure_clusters / reward_hack / sql."""
        dispatch: dict[str, Callable[..., Any]] = {
            "regression": self.regression,
            "failure_clusters": self.failure_clusters,
            "reward_hack": self.reward_hack,
            "sql": self.sql,
        }
        return dispatch[name](**kwargs)

    def close(self) -> None:
        self.conn.close()
