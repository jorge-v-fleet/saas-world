"""Random-policy rollouts — traverse the world uniformly at random, one trajectory per episode.

Why this exists: to characterise the *base distribution* of the environment. A random policy that
picks legal actions from the live action space and lets the sim clock run gives us the reward/steps
spread you get from doing nothing intelligent — the floor every real agent must beat, and a cheap
smoke test that the whole loop (generate -> reset -> step -> terminate -> score) holds together.

Design:
  - Each episode runs over a *fresh* scenario instance minted by the Seeding Engine from a random
    seed (`engine.generate`), so we sample over worlds, not just over one hand-authored scenario.
    (`--archetype` picks the template; by default we rotate over every template in data/templates.)
  - The policy is `RandomPolicy`: sample a catalog verb, fill its args from ids observed in the live
    world snapshot, step. Invalid/denied actions are non-terminal (the env surfaces them as errors),
    so a bad random draw just wastes a turn — never crashes the episode.
  - Only `advance` verbs move time, and an episode terminates when the clock crosses the eval
    horizon. So the policy is biased toward advancing (`--advance-prob`), and if the step budget is
    nearly spent without terminating we force a horizon-crossing wait — every episode ends scored.
  - We honour the env contract: the moment `step()` returns `done`, we stop navigating and start the
    next trajectory.

Everything is in-process against `SaasWorldEnvironment` (no server, no API key — the NPC parser
replays from the committed cassette) and reproducible from one `--master-seed`.

Output: one standard run dir per episode (`runs/rollouts/rollout-<NNNN>-<archetype>/` with
manifest.json + trajectory.jsonl + score.json — the same layout `scripts/pm_agent_llm.py` writes,
via the shared `saasworld.trajectory.actionlog` writer) plus a `rollouts-summary.json` distribution
aggregate. The inspector reads agent runs and random rollouts identically.

    uv run python scripts/random_rollouts.py --episodes 50      # -> runs/rollouts/
    uv run python scripts/random_rollouts.py --episodes 20 --archetype hidden-critical-blocker
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saasworld.engine import generate
from saasworld.engine.substrate import TEMPLATES
from saasworld.openenv.environment import SaasWorldEnvironment
from saasworld.openenv.types import SaasWorldAction
from saasworld.trajectory.actionlog import step_row, write_run

_REPO = Path(__file__).resolve().parents[1]

# Small plausible vocabularies so a random draw *occasionally* lands a scoring action — enough to
# spread the reward distribution above zero, not enough to make the policy competent.
_DECISION_TYPES = ("gonogo", "reprioritize", "escalate", "descope")
_DECISION_ACTIONS = ("reschedule", "cut_scope", "proceed", "hold")
_STATUSES = ("todo", "in_progress", "blocked", "done")
_WORDS = ("ping", "status", "blocker", "risk", "eta", "launch", "review", "help", "fyi", "sync")


# --------------------------------------------------------------------------------------------------
# Reading ids out of the live world snapshot
# --------------------------------------------------------------------------------------------------

def _flatten_ids(node: Any, prefix: str = "") -> dict[str, dict[str, Any]]:
    """Rebuild dotted entity ids from a nested partition (`{'task': {'psp': {...}}}` -> `task.psp`).

    A dict with any non-dict value is treated as a leaf entity; otherwise we descend one segment.
    Matches the loader's `_nest`, which walks a dotted id into nested dicts.
    """
    if not isinstance(node, dict):
        return {}
    if prefix and any(not isinstance(v, dict) for v in node.values()):
        return {prefix: node}
    out: dict[str, dict[str, Any]] = {}
    for key, val in node.items():
        out.update(_flatten_ids(val, f"{prefix}.{key}" if prefix else key))
    return out


@dataclass
class WorldRefs:
    """Handles to every id the agent could legally name, pulled fresh from a snapshot each turn."""

    people: list[str]
    projects: list[str]
    tasks: list[str]
    blockers: list[str]
    channels: list[str]
    docs: list[str]
    meetings: list[str]

    @classmethod
    def from_snapshot(cls, s: dict[str, Any]) -> WorldRefs:
        return cls(
            people=list(s.get("org", {})),
            projects=list(_flatten_ids(s.get("projects", {}))),
            tasks=list(_flatten_ids(s.get("tasks", {}))),
            blockers=list(_flatten_ids(s.get("blockers", {}))),
            channels=list(s.get("chat", {})),
            docs=[str(d["id"]) for d in s.get("docs", []) if isinstance(d, dict) and d.get("id")],
            meetings=[str(c["id"]) for c in s.get("calendar", [])
                      if isinstance(c, dict) and c.get("id")],
        )

    @property
    def refs(self) -> list[str]:
        """Everything a `refs` arg (structured pointer the grader reads) could point at."""
        return [*self.tasks, *self.blockers, *self.projects]


# --------------------------------------------------------------------------------------------------
# The random policy
# --------------------------------------------------------------------------------------------------

class RandomPolicy:
    """Uniformly samples a legal-ish verb + args from what the current snapshot exposes.

    Not every draw is valid (e.g. attending a meeting outside its window) — that's intentional: the
    env rejects it as a non-terminal error and we move on. The one thing we *do* steer is time: the
    episode can only end by advancing, so `advance_prob` of the time we emit a `wait`.
    """

    def __init__(self, rng: random.Random, advance_prob: float) -> None:
        self.rng = rng
        self.advance_prob = advance_prob

    def _pick(self, seq: list[str]) -> str | None:
        return self.rng.choice(seq) if seq else None

    def _text(self) -> str:
        return " ".join(self.rng.choice(_WORDS) for _ in range(self.rng.randint(1, 5)))

    def _offset(self) -> str:
        return f"D{self.rng.randint(1, 8)}T{self.rng.randint(9, 17):02d}:00"

    def act(self, snapshot: dict[str, Any]) -> SaasWorldAction:
        r = WorldRefs.from_snapshot(snapshot)
        if self.rng.random() < self.advance_prob:
            return SaasWorldAction("wait", {"duration": self.rng.choice([30, 60, 120, 240, 480])})

        verb = self.rng.choice([
            "read_inbox", "read_channel", "get_calendar", "get_tasks", "read_doc",
            "get_people", "get_transcript", "send_message", "send_email", "create_task",
            "update_task", "book_meeting", "create_doc", "update_doc", "record_decision",
            "attend_meeting",
        ])
        return SaasWorldAction(verb, self._args(verb, r))

    def _args(self, verb: str, r: WorldRefs) -> dict[str, Any]:  # noqa: PLR0911 - flat verb table
        rng = self.rng
        if verb == "read_channel":
            return {"channel": self._pick(r.channels)} if r.channels else {}
        if verb == "read_doc":
            return {"doc": self._pick(r.docs)} if r.docs else {}
        if verb == "get_transcript":
            return {"meeting": self._pick(r.meetings)} if r.meetings else {}
        if verb == "get_tasks":
            return {"project": self._pick(r.projects)} if r.projects and rng.random() < 0.5 else {}
        if verb == "send_message":
            to = self._pick([*r.people, *r.channels])
            args: dict[str, Any] = {"to": to, "body": self._text()}
            if r.refs and rng.random() < 0.5:
                args["refs"] = rng.sample(r.refs, k=min(2, len(r.refs)))
            return args
        if verb == "send_email":
            return {"to": self._pick(r.people), "subject": self._text(), "body": self._text()}
        if verb == "create_task":
            return {"project": self._pick(r.projects), "title": self._text(),
                    "owner": self._pick(r.people), "due": self._offset()}
        if verb == "update_task":
            return {"task": self._pick(r.tasks), "set": {"status": rng.choice(_STATUSES)}}
        if verb == "book_meeting":
            return {"title": self._text(),
                    "attendees": rng.sample(r.people, k=min(3, len(r.people))) if r.people else [],
                    "at": self._offset(), "duration": rng.choice([30, 60])}
        if verb == "create_doc":
            return {"title": self._text(), "body": self._text()}
        if verb == "update_doc":
            return {"doc": self._pick(r.docs), "body": self._text()} if r.docs else {}
        if verb == "record_decision":
            return {"about": self._pick([*r.projects, *r.tasks]),
                    "type": rng.choice(_DECISION_TYPES), "action": rng.choice(_DECISION_ACTIONS),
                    "new_date": self._offset(), "owner": self._pick(r.people),
                    "rationale": self._text()}
        if verb == "attend_meeting":
            return {"meeting": self._pick(r.meetings)} if r.meetings else {}
        return {}  # observe verbs with no args


# --------------------------------------------------------------------------------------------------
# One episode
# --------------------------------------------------------------------------------------------------

@dataclass
class Rollout:
    episode: int
    archetype: str
    seed: int
    run_id: str | None
    steps: int
    errors: int
    sim_time: int
    horizon: int
    reward: float | None
    forced_terminal: bool
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    score: dict[str, Any] | None = None


def run_episode(
    episode: int, archetype: str, scenario_seed: int, policy_rng: random.Random,
    advance_prob: float, max_steps: int, workdir: Path,
) -> Rollout:
    """Mint a random world, drive the random policy until the env says `done`, capture the trace."""
    inst = generate(archetype, scenario_seed, workdir / f"{archetype}-{scenario_seed}")
    env = SaasWorldEnvironment()
    obs = env.reset(str(inst.out_dir), seed=scenario_seed)
    horizon = int(obs.metadata.get("horizon", 0))
    policy = RandomPolicy(policy_rng, advance_prob)

    trace: list[dict[str, Any]] = []
    errors = forced = 0
    snapshot = obs.state
    for step in range(1, max_steps + 1):
        # Safety net: if we're about to run out of budget and haven't terminated, jump the horizon
        # so every episode ends with a real score rather than a truncation.
        if step == max_steps and not obs.done and horizon:
            action = SaasWorldAction("wait", {"duration": max(1, horizon - obs.sim_time + 60)})
            forced = 1
        else:
            action = policy.act(snapshot)

        obs = env.step(action)
        errors += bool(obs.metadata.get("error"))
        trace.append(step_row(step, action.verb, action.args, obs))  # shared standard row schema
        snapshot = obs.state
        if obs.done:
            break

    return Rollout(
        episode=episode, archetype=archetype, seed=scenario_seed, run_id=env.state.run_id,
        steps=len(trace), errors=errors, sim_time=obs.sim_time, horizon=horizon,
        reward=obs.reward, forced_terminal=bool(forced), trajectory=trace,
        score=obs.metadata.get("score"),
    )


# --------------------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------------------

def _write_run_dir(out: Path, roll: Rollout) -> Path:
    """Persist one rollout as a standard run dir (same layout as the LLM agent's runs)."""
    run_dir = out / f"rollout-{roll.episode:04d}-{roll.archetype}"
    manifest = {
        "kind": "random", "scenario": roll.archetype, "archetype": roll.archetype,
        "seed": roll.seed, "run_id": roll.run_id, "actions": roll.steps, "errors": roll.errors,
        "horizon": roll.horizon, "sim_time": roll.sim_time,
        "forced_terminal": roll.forced_terminal, "final_reward": roll.reward,
    }
    write_run(run_dir, manifest=manifest, rows=roll.trajectory, score=roll.score)
    return run_dir


def _archetypes(chosen: str | None) -> list[str]:
    if chosen:
        return [chosen]
    return sorted(p.stem for p in TEMPLATES.glob("*.json"))


def _summary(rollouts: list[Rollout]) -> dict[str, Any]:
    rewards = [r.reward for r in rollouts if r.reward is not None]
    steps = [r.steps for r in rollouts]
    return {
        "episodes": len(rollouts),
        "scored": len(rewards),
        "forced_terminal": sum(r.forced_terminal for r in rollouts),
        "reward": {
            "mean": round(statistics.fmean(rewards), 4) if rewards else None,
            "max": round(max(rewards), 4) if rewards else None,
            "min": round(min(rewards), 4) if rewards else None,
            "nonzero": sum(x > 0 for x in rewards),
        },
        "steps": {"mean": round(statistics.fmean(steps), 1), "max": max(steps), "min": min(steps)},
        "total_errors": sum(r.errors for r in rollouts),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Random-policy trajectory rollouts over saas-world.")
    ap.add_argument("--episodes", type=int, default=20, help="number of trajectories to roll out")
    ap.add_argument("--archetype", default=None, help="template id (default: rotate over all)")
    ap.add_argument("--master-seed", type=int, default=0, help="seeds the whole run reproducibly")
    ap.add_argument("--advance-prob", type=float, default=0.35, help="P(a step advances the clock)")
    ap.add_argument("--max-steps", type=int, default=120, help="per-episode step budget (safety)")
    ap.add_argument("--out", default=str(_REPO / "runs" / "rollouts"),
                    help="dir to write per-episode run dirs into (default: runs/rollouts/)")
    args = ap.parse_args()

    # A random policy sends arbitrary message bodies the NPC cassette can't render, so the parser
    # degrades to a bare ack every time — expected here, so silence that per-reply warning.
    logging.getLogger("saasworld.npc.engine").setLevel(logging.ERROR)

    master = random.Random(args.master_seed)
    archetypes = _archetypes(args.archetype)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rollouts: list[Rollout] = []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for ep in range(1, args.episodes + 1):
            archetype = archetypes[(ep - 1) % len(archetypes)]
            scenario_seed = master.randrange(1, 2**31)          # a fresh random world
            policy_rng = random.Random(master.randrange(2**31))  # an independent action stream
            roll = run_episode(ep, archetype, scenario_seed, policy_rng,
                               args.advance_prob, args.max_steps, workdir)
            rollouts.append(roll)
            run_dir = _write_run_dir(out, roll)  # one standard run dir per episode
            r = "n/a" if roll.reward is None else f"{roll.reward:.3f}"
            flag = " (forced)" if roll.forced_terminal else ""
            print(f"  ep {ep:>3}  {archetype:<20} seed={scenario_seed:<11} "
                  f"steps={roll.steps:>3} err={roll.errors:>3} reward={r}{flag} -> {run_dir.name}")

    summary = _summary(rollouts)
    (out / "rollouts-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nrandom-rollout distribution over {summary['episodes']} episodes:")
    print(f"  reward   mean={summary['reward']['mean']}  min={summary['reward']['min']}  "
          f"max={summary['reward']['max']}  nonzero={summary['reward']['nonzero']}")
    print(f"  steps    mean={summary['steps']['mean']}  min={summary['steps']['min']}  "
          f"max={summary['steps']['max']}")
    print(f"  errors   total={summary['total_errors']}   forced-terminal="
          f"{summary['forced_terminal']}")
    print(f"\nwrote {args.episodes} run dir(s) + rollouts-summary.json under {out}/")


if __name__ == "__main__":
    main()
