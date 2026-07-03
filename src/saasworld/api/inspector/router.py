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
import math
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
    inner = raw.get("breakdown")
    b = inner if isinstance(inner, dict) else raw
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


# ── cohort (cross-run distribution) ──────────────────────────────────────────
# Verbs that only read world state; anything else that ran without error mutated it. Used as the
# reward-hack "real delta" proxy when a run has no canonical events.jsonl.
_READ_VERBS = {
    "read_inbox", "read_channel", "get_calendar", "get_tasks", "read_doc",
    "get_people", "get_transcript", "wait", "attend_meeting",
}
_MESSAGE_VERBS = {"send_message", "send_email"}


def _run_folder(run_id: str) -> str:
    """Top-level grouping key — mirrors the UI's runFolder() (last '/' splits folder/leaf)."""
    return run_id[: run_id.rfind("/")] if "/" in run_id else "(root)"


def _stats(vals: list[float]) -> dict[str, Any]:
    n = len(vals)
    if not n:
        return {"mean": None, "min": None, "max": None, "stddev": 0.0,
                "ci_low": None, "ci_high": None}
    mean = sum(vals) / n
    stddev = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    half = 1.96 * stddev / math.sqrt(n) if n > 1 else 0.0
    return {"mean": mean, "min": min(vals), "max": max(vals), "stddev": stddev,
            "ci_low": mean - half, "ci_high": mean + half}


def _reward_hist(vals: list[float], bins: int = 10) -> list[int]:
    hist = [0] * bins
    for v in vals:
        idx = min(bins - 1, max(0, int(v * bins)))  # clamp [0,1] into fixed bins
        hist[idx] += 1
    return hist


def _n_messages(rows: list[dict[str, Any]]) -> int:
    return sum(1 for r in rows if r.get("verb") in _MESSAGE_VERBS)


def _n_real_deltas(d: Path, rows: list[dict[str, Any]]) -> int:
    """Real state changes: events.jsonl rows with a non-empty delta; else mutate-ish, error-free
    actions (a run that only reads/waits or errors out changed nothing)."""
    events = _read_jsonl(d / "events.jsonl") if (d / "events.jsonl").exists() else None
    if events is not None:
        return sum(1 for e in events if e.get("delta"))
    return sum(1 for r in rows
               if r.get("verb") not in _READ_VERBS and not r.get("error"))


@router.get("/api/cohort")
def get_cohort(folder: str) -> JSONResponse:
    base = _runs_dir()
    empty = {"folder": folder, "n": 0, "rewards": [], "reward_hist": [0] * 10,
             "per_archetype": [], "checkpoints": [], "scatter": [],
             "mean": None, "min": None, "max": None, "stddev": 0.0,
             "ci_low": None, "ci_high": None}
    if not base.is_dir():
        return JSONResponse(empty)

    dirs = [d for d in _find_run_dirs(base)
            if _run_folder(d.relative_to(base).as_posix()) == folder]
    if not dirs:
        return JSONResponse(empty)

    rewards: list[float] = []
    by_arch: dict[str, list[float]] = {}
    pred_n: dict[str, int] = {}
    pred_pass: dict[str, int] = {}
    heatmap: list[dict[str, Any]] = []
    scatter: list[dict[str, Any]] = []

    for d in dirs:
        run_id = d.relative_to(base).as_posix()
        manifest = _read_json(d / "manifest.json") or {}
        rows = _read_jsonl(d / "trajectory.jsonl")
        sc_raw = _read_json(d / "score.json") if (d / "score.json").exists() else None
        score = _normalize_score(sc_raw)
        reward = _final_reward(manifest, score)

        if isinstance(reward, (int, float)):
            rewards.append(float(reward))
            arch = manifest.get("archetype") or manifest.get("scenario") or run_id
            by_arch.setdefault(arch, []).append(float(reward))

        preds = [p for cp in (score or {}).get("checkpoints", []) for p in cp.get("predicates", [])]
        results: dict[str, int] = {}
        for p in preds:
            pid = p.get("id")
            if pid is None:
                continue
            ok = 1 if p.get("status") == "pass" else 0
            pred_n[pid] = pred_n.get(pid, 0) + 1
            pred_pass[pid] = pred_pass.get(pid, 0) + ok
            results[pid] = ok
        heatmap.append({"run_id": run_id, "results": results})

        scatter.append({
            "run_id": run_id,
            "n_messages": _n_messages(rows),
            "n_real_deltas": _n_real_deltas(d, rows),
            "reward": reward if isinstance(reward, (int, float)) else None,
        })

    per_archetype = []
    for arch in sorted(by_arch):
        s = _stats(by_arch[arch])
        per_archetype.append({"archetype": arch, "n": len(by_arch[arch]),
                              "reward_mean": s["mean"], "reward_ci_low": s["ci_low"],
                              "reward_ci_high": s["ci_high"]})
    checkpoints = [{"id": pid, "n": pred_n[pid], "pass": pred_pass[pid],
                    "pass_rate": pred_pass[pid] / pred_n[pid]}
                   for pid in sorted(pred_n)]

    return JSONResponse({
        "folder": folder, "n": len(dirs), "rewards": rewards,
        "reward_hist": _reward_hist(rewards), **_stats(rewards),
        "per_archetype": per_archetype,
        "checkpoints": {"per_id": checkpoints, "heatmap": heatmap},
        "scatter": scatter,
    })


@router.get("/api/runs/{run_id:path}")
def get_run(run_id: str) -> JSONResponse:
    base = _runs_dir().resolve()
    d = (base / run_id).resolve()
    if base not in d.parents or not d.is_dir():  # no path traversal outside runs/
        raise HTTPException(status_code=404, detail="run not found")
    manifest = _read_json(d / "manifest.json")
    rows = _read_jsonl(d / "trajectory.jsonl")
    score = _normalize_score(_read_json(d / "score.json"))
    messages = _read_json(d / "messages.json")  # LLM transcript; ~100KB, inline for local inspector
    kind = _sniff_kind(manifest, rows[0] if rows else None)
    # Canonical kernel event log for the replay timeline. Generators persist events.jsonl; cli runs
    # have their canonical envelopes directly in trajectory.jsonl. Opening state seeds delta-fold.
    events_file = d / "events.jsonl"
    if events_file.exists():
        events = _read_jsonl(events_file)
    elif kind == "cli":
        events = rows
    else:
        events = []
    opening = _read_json(d / "snapshots" / "0.json")
    return JSONResponse({
        "run_id": d.relative_to(base).as_posix(),
        "kind": kind,
        "manifest": manifest,
        "trajectory": [_normalize_row(i, r) for i, r in enumerate(rows)],
        "score": score,
        "has_messages": (d / "messages.json").exists(),
        "messages": messages,
        "events": events,
        "opening": opening,
        "has_events": bool(events),
    })
