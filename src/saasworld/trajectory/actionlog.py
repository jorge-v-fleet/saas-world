"""Standard action-stream run: the shared on-disk form for policy-driven episodes.

Both trajectory generators — the LLM PM agent (``scripts/pm_agent_llm.py``) and the random-policy
rollouts (``scripts/random_rollouts.py``) — emit this exact layout so one inspector reads them
uniformly:

    runs/<run_id>/
      manifest.json      run provenance: kind, scenario, seed/model, actions, horizon, final_reward
      trajectory.jsonl   one row per policy step (schema below)
      score.json         evaluator breakdown, present once the episode crossed the horizon
      messages.json      LLM transcript (agent runs only; omitted for random rollouts)

Row schema (one JSON object per line)::

    {"turn", "verb", "args", "sim_time", "done", "reward", "events", "error"}

This is deliberately NOT the canonical kernel event log (``TrajectoryStore``): that records every
event incl. NPC replies + applied deltas. This is the *policy's* action stream — what the agent
chose and the coarse events each action triggered. The two are complementary and both round-trip
through the same evaluator, so the ``score.json`` here matches ``saasworld run-eval`` exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TRAJECTORY_FILE = "trajectory.jsonl"


def step_row(turn: int, verb: str, args: dict[str, Any], obs: Any,
             *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one standard trajectory row from a ``SaasWorldObservation`` (from ``env.step``)."""
    meta = obs.metadata or {}
    row = {
        "turn": turn,
        "verb": verb,
        "args": args,
        "sim_time": obs.sim_time,
        "done": obs.done,
        "reward": obs.reward,
        "events": [f"{e.get('actor')}->{e.get('kind')}" for e in (obs.events or [])],
        "error": meta.get("error"),
    }
    if extra:
        row.update(extra)
    return row


def write_run(out_dir: str | Path, *, manifest: dict[str, Any], rows: list[dict[str, Any]],
              score: dict[str, Any] | None = None,
              messages: list[dict[str, Any]] | None = None) -> Path:
    """Write the standard run layout to ``out_dir``; returns the directory."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    with (out / TRAJECTORY_FILE).open("w") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    if score is not None:
        (out / "score.json").write_text(json.dumps(score, indent=2, default=str) + "\n")
    if messages is not None:
        (out / "messages.json").write_text(json.dumps(messages, indent=2, default=str) + "\n")
    return out
