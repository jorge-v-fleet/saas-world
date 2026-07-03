"""Read-only inspector API + SPA over ``runs/``.

Endpoints (all under ``/inspector``):
    GET /inspector                serve the single-page app
    GET /inspector/api/runs       list runs (dir scan; sniffs kind; cheap summary)
    GET /inspector/api/runs/{id}  one run: manifest + normalized trajectory rows + score

Runs live under ``$SAASWORLD_RUNS_DIR`` (default ``<repo>/runs``). Three producers land here and are
normalized to one shape so the UI is producer-agnostic:
    - agent   (scripts/pm_agent_llm.py)     manifest.kind == "agent"
    - random  (scripts/random_rollouts.py)  manifest.kind == "random"
    - cli     (TrajectoryStore run-eval)    canonical event log, no manifest.kind
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(prefix="/inspector", tags=["inspector"])

_HERE = Path(__file__).resolve().parent
_INDEX = _HERE / "index.html"
_REPO = _HERE.parents[3]


def _runs_dir() -> Path:
    return Path(os.environ.get("SAASWORLD_RUNS_DIR", _REPO / "runs"))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    return rows


def _sniff_kind(manifest: dict[str, Any] | None, first_row: dict[str, Any] | None) -> str:
    """Producer of a run: manifest.kind wins; else canonical event log => 'cli'."""
    if manifest and manifest.get("kind"):
        return str(manifest["kind"])
    if first_row and "verb" in first_row:
        return "agent"          # action-stream row with no manifest.kind
    if first_row and ("seq" in first_row or "kind" in first_row):
        return "cli"            # canonical kernel event log
    return "unknown"


def _normalize_score(raw: Any) -> dict[str, Any] | None:
    """CLI score.json wraps the breakdown under 'breakdown'; the env writes it flat. Unify."""
    if not isinstance(raw, dict):
        return None
    b = raw.get("breakdown") if isinstance(raw.get("breakdown"), dict) else raw
    return {
        "final": b.get("final"),
        "weights_sum": b.get("weights_sum"),
        "checkpoints": b.get("checkpoints", []),
        "artifact_results": b.get("artifact_results", []),
    }


def _final_reward(manifest: dict[str, Any] | None, score: dict[str, Any] | None) -> Any:
    if manifest and manifest.get("final_reward") is not None:
        return manifest["final_reward"]
    return score.get("final") if score else None


def _normalize_row(i: int, row: dict[str, Any]) -> dict[str, Any]:
    """Fold either row schema (action-stream or canonical event) into one display row."""
    if "verb" in row:  # action-stream (agent / random)
        return {
            "i": i, "actor": "agent", "label": row.get("verb"), "args": row.get("args"),
            "sim_time": row.get("sim_time"), "reward": row.get("reward"),
            "done": row.get("done"), "events": row.get("events") or [],
            "error": row.get("error"), "caused_by": None,
        }
    return {  # canonical kernel event log
        "i": i, "actor": row.get("actor"), "label": row.get("kind"), "args": row.get("payload"),
        "sim_time": row.get("sim_time"), "reward": None, "done": None,
        "events": [], "error": None, "caused_by": row.get("caused_by"),
        "seq": row.get("seq"), "delta": row.get("delta"),
    }


def _find_run_dirs(base: Path) -> list[Path]:
    """Any dir at any depth under `base` holding a manifest.json or trajectory.jsonl is a run.

    Recursive so nested groupings (e.g. runs/rollouts/rollout-*/) are discovered uniformly.
    """
    seen: set[Path] = set()
    for marker in ("manifest.json", "trajectory.jsonl"):
        seen.update(p.parent for p in base.rglob(marker))
    return sorted(seen)


def _summarize(d: Path, base: Path) -> dict[str, Any] | None:
    manifest = _read_json(d / "manifest.json") if (d / "manifest.json").exists() else None
    traj = d / "trajectory.jsonl"
    if manifest is None and not traj.exists():
        return None  # not a run dir
    rows = _read_jsonl(traj)
    score = _normalize_score(_read_json(d / "score.json")) if (d / "score.json").exists() else None
    kind = _sniff_kind(manifest, rows[0] if rows else None)
    scenario = (manifest or {}).get("scenario") or (manifest or {}).get("scenario_id")
    run_id = d.relative_to(base).as_posix()  # path relative to runs/ so nested runs are addressable
    return {
        "run_id": run_id,
        "kind": kind,
        "scenario": scenario or run_id,
        "actions": (manifest or {}).get("actions", len(rows)),
        "final_reward": _final_reward(manifest, score),
        "has_score": score is not None,
        "has_messages": (d / "messages.json").exists(),
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(_INDEX.read_text())


@router.get("/api/runs")
def list_runs() -> JSONResponse:
    base = _runs_dir()
    runs: list[dict[str, Any]] = []
    if base.is_dir():
        for d in _find_run_dirs(base):
            summary = _summarize(d, base)
            if summary:
                runs.append(summary)
    runs.sort(key=lambda r: r["run_id"], reverse=True)
    return JSONResponse({"runs_dir": str(base), "count": len(runs), "runs": runs})


@router.get("/api/runs/{run_id:path}")
def get_run(run_id: str) -> JSONResponse:
    base = _runs_dir().resolve()
    d = (base / run_id).resolve()
    if base not in d.parents or not d.is_dir():  # no path traversal outside runs/
        raise HTTPException(status_code=404, detail="run not found")
    manifest = _read_json(d / "manifest.json")
    rows = _read_jsonl(d / "trajectory.jsonl")
    score = _normalize_score(_read_json(d / "score.json"))
    return JSONResponse({
        "run_id": d.relative_to(base).as_posix(),
        "kind": _sniff_kind(manifest, rows[0] if rows else None),
        "manifest": manifest,
        "trajectory": [_normalize_row(i, r) for i, r in enumerate(rows)],
        "score": score,
        "has_messages": (d / "messages.json").exists(),
    })
