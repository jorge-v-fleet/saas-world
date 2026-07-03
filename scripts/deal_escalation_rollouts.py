"""Competence-parameterised rollouts over the `deal-escalation` scenario family.

Why this exists: `random_rollouts.py` characterises the *floor* (a blind random policy). This one
characterises the *spectrum* — a knob `c` (competence) per episode that dials how reliably the
policy performs the scoring backbone, so the reward distribution spreads across the full [0,1] range
and every eval predicate lands in-between (never all-pass, never all-fail). That's what a dataset
for training/eval-calibration needs: graded difficulty, not just a floor.

Design (mirrors `random_rollouts.py`; same run-dir layout via `saasworld.trajectory.actionlog`):
  - Each episode mints a *fresh* deal-escalation instance from a random seed (`engine.generate`) and
    drives the real `SaasWorldEnvironment`, so the FINAL score.json comes from the real evaluator
    (`eval/score.py`) through the env's terminal reward — pass-rates are trustworthy.
  - The instance's ids are resolved per-episode from the frozen `eval.json` (AE/CS/stakeholder + the
    correct_set) and `seed.json` (true_feasible); the Eng holder comes from the generate summary.
  - Competence `c ~ Uniform(c_min, c_max)`. Each of the 5 scoring backbone steps fires independently
    with probability `c`. For the decision step the CORRECT action is chosen with probability
    `q(c) = c ** q_exp` (else a wrong one), so `commit_recorded` and `correct_commit` decouple —
    correct_commit's pass-rate sits strictly below commit_recorded's.
  - The Eng reveal (`feasibility_surfaced`) is a system-only denied field: no agent write path fires
    it (verified — a crafted send_message to the holder does NOT flip it via the replay cassette).
    So when the ask-Eng step fires we (a) emit the visible send_message to the holder AND (b) model
    the reveal deterministically by scheduling a system `reveal` on the kernel — exactly as
    `engine/solvers.py` applies its `fallback_deltas`. Legitimate here: this is a distribution
    GENERATOR consulting ground truth to construct trajectories, not a graded agent.
  - Fully deterministic off `--master-seed` + episode index (no wall-clock, no global RNG).

Output: one standard run dir per episode (manifest.json + trajectory.jsonl + score.json) plus a
`rollouts-summary.json` with the reward histogram and per-predicate pass-rates. Canonical event logs
(events.jsonl + snapshots) are persisted for only the first `--keep-canonical` episodes to keep disk
sane at 2000 while leaving the inspector Timeline rich examples.

    uv run python scripts/deal_escalation_rollouts.py --episodes 200          # tune batch
    uv run python scripts/deal_escalation_rollouts.py --episodes 2000         # full run
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saasworld.engine import generate
from saasworld.openenv.environment import SaasWorldEnvironment
from saasworld.openenv.types import SaasWorldAction
from saasworld.trajectory.actionlog import step_row, write_run

_REPO = Path(__file__).resolve().parents[1]
ARCHETYPE = "deal-escalation"
DEAL = "deal"
ACCOUNT_RISK = "account_risk"
_ALL_ACTIONS = ("commit", "decline", "counter_offer")
_PREDICATES = ("feasibility_surfaced", "commit_recorded", "correct_commit",
               "informed_sales", "informed_cs", "stakeholder_informed")


# --------------------------------------------------------------------------------------------------
# Per-instance id resolution (read the frozen instance the evaluator will actually grade against)
# --------------------------------------------------------------------------------------------------

@dataclass
class Refs:
    ae: str            # Account Executive (sales)
    cs: str            # Customer Success rep
    stakeholder: str   # CTO stakeholder
    holder: str        # Eng holder — the reveal source
    correct_set: list[str]
    true_feasible: bool


def _to_of(expr: str) -> str:
    """Pull the `to=='<id>'` recipient out of an eval message-existence assert."""
    m = re.search(r"to=='([^']+)'", expr)
    if not m:
        raise ValueError(f"no recipient in assert {expr!r}")
    return m.group(1)


def resolve_refs(instance_dir: Path, holder: str) -> Refs:
    """Resolve the graded ids straight from the instance's own eval.json / seed.json."""
    ev = json.loads((instance_dir / "eval.json").read_text())
    preds = {p["id"]: p for p in ev["checkpoints"][0]["predicates"]}
    seed = json.loads((instance_dir / "seed.json").read_text())
    return Refs(
        ae=_to_of(preds["informed_sales"]["assert"]["exists"]),
        cs=_to_of(preds["informed_cs"]["assert"]["exists"]),
        stakeholder=_to_of(preds["stakeholder_informed"]["assert"]["exists"]),
        holder=holder,
        correct_set=list(preds["correct_commit"]["assert"]["in"]["set"]),
        true_feasible=bool(seed["projects"][0]["true_feasible"]),
    )


# --------------------------------------------------------------------------------------------------
# The competence-parameterised policy
# --------------------------------------------------------------------------------------------------

@dataclass
class Dist:
    c_min: float
    c_max: float
    q_exp: float  # q(c) = c ** q_exp — governs P(correct action | decision recorded)


class CompetencePolicy:
    """Draws a competence `c`, then fires each backbone step independently with probability `c`.

    Not a navigator (unlike RandomPolicy): the backbone is a fixed 5-step script, gated by `c`, with
    a couple of no-op observes interleaved for realism. Determinism comes from a single per-episode
    rng seeded off the master seed."""

    def __init__(self, rng: random.Random, dist: Dist) -> None:
        self.rng = rng
        self.dist = dist
        self.c = rng.uniform(dist.c_min, dist.c_max)

    def _fire(self) -> bool:
        return self.rng.random() < self.c

    def _action(self, refs: Refs) -> str:
        """The recorded commit action: correct w.p. q(c), else a wrong one."""
        if self.rng.random() < self.c ** self.dist.q_exp:
            return refs.correct_set[0]
        wrong = [a for a in _ALL_ACTIONS if a not in refs.correct_set]
        return self.rng.choice(wrong)


# --------------------------------------------------------------------------------------------------
# One episode
# --------------------------------------------------------------------------------------------------

@dataclass
class Rollout:
    episode: int
    seed: int
    competence: float
    run_id: str | None
    steps: int
    errors: int
    sim_time: int
    horizon: int
    reward: float | None
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    score: dict[str, Any] | None = None
    canonical: dict[str, Any] | None = None


def run_episode(
    episode: int, seed: int, rng: random.Random, dist: Dist, workdir: Path, keep_canonical: bool,
) -> Rollout:
    """Mint a fresh instance, drive the competence-gated backbone through the real env, score it."""
    inst = generate(ARCHETYPE, seed, workdir / f"{ARCHETYPE}-{seed}")
    refs = resolve_refs(inst.out_dir, inst.summary["holder"])
    env = SaasWorldEnvironment()
    obs = env.reset(str(inst.out_dir), seed=seed)
    horizon = int(obs.metadata.get("horizon", 0))
    policy = CompetencePolicy(rng, dist)

    trace: list[dict[str, Any]] = []
    errors = 0

    def do(verb: str, args: dict[str, Any]) -> None:
        nonlocal obs
        obs = env.step(SaasWorldAction(verb, args))
        errors_here = bool(obs.metadata.get("error"))
        nonlocal errors
        errors += errors_here
        trace.append(step_row(len(trace) + 1, verb, args, obs))

    do("read_inbox", {})  # realism: skim the AE's kickoff email

    # 1) Ask Eng about the deal -> the reveal that flips feasibility_surfaced (system-sourced).
    if policy._fire():
        do("send_message", {"to": refs.holder, "refs": [DEAL],
                            "body": "Can Eng land the deal by the promised date?"})
        env._kernel.schedule(  # model the reveal deterministically, like solvers' fallback_deltas
            env._kernel.now() + 50, "system", "reveal",
            {"deltas": [{"op": "set",
                         "path": "projects.deal.feasibility_surfaced", "value": True}]})

    do("read_channel", {"channel": "chan.deal"})  # realism

    # 2) Record the commit decision (commit_recorded); correct action w.p. q(c) (correct_commit).
    if policy._fire():
        do("record_decision", {"about": DEAL, "type": "commit", "action": policy._action(refs),
                               "rationale": "Commit call grounded in Eng's feasibility read."})

    # 3-5) Inform Sales / CS / stakeholder, each with the deterministic ref the grader reads.
    if policy._fire():
        do("send_message", {"to": refs.ae, "body": "Commit call on the deal.", "refs": [DEAL]})
    do("get_tasks", {})  # realism
    if policy._fire():
        do("send_message", {"to": refs.cs, "refs": [ACCOUNT_RISK],
                            "body": "Weighed the account risk."})
    if policy._fire():
        do("send_message", {"to": refs.stakeholder, "body": "Recorded the commit decision.",
                            "refs": [DEAL]})

    # Advance past the horizon so the episode ends with a real, evaluator-produced score.
    if not obs.done and horizon:
        do("wait", {"duration": max(1, horizon - obs.sim_time + 60)})

    return Rollout(
        episode=episode, seed=seed, competence=round(policy.c, 4), run_id=env.state.run_id,
        steps=len(trace), errors=errors, sim_time=obs.sim_time, horizon=horizon,
        reward=obs.reward, trajectory=trace, score=obs.metadata.get("score"),
        canonical=env.canonical_trajectory() if keep_canonical else None,
    )


# --------------------------------------------------------------------------------------------------
# Driver + metrics
# --------------------------------------------------------------------------------------------------

def _write_run_dir(out: Path, roll: Rollout) -> Path:
    run_dir = out / f"rollout-{roll.episode:04d}"
    manifest = {
        "kind": "mixed", "scenario": ARCHETYPE, "archetype": ARCHETYPE, "seed": roll.seed,
        "competence": roll.competence, "run_id": roll.run_id, "actions": roll.steps,
        "errors": roll.errors, "horizon": roll.horizon, "sim_time": roll.sim_time,
        "final_reward": roll.reward,
    }
    write_run(run_dir, manifest=manifest, rows=roll.trajectory, score=roll.score,
              canonical=roll.canonical)
    return run_dir


def _pred_status(score: dict[str, Any] | None) -> dict[str, str]:
    if not score:
        return {}
    return {p["id"]: p["status"]
            for cp in score.get("checkpoints", []) for p in cp.get("predicates", [])}


def _histogram(rewards: list[float], bins: int = 10) -> list[int]:
    """Count rewards into `bins` equal bins over [0,1]; 1.0 lands in the top bin."""
    hist = [0] * bins
    for r in rewards:
        idx = min(bins - 1, int(r * bins))
        hist[idx] += 1
    return hist


def _summary(rollouts: list[Rollout], dist: Dist) -> dict[str, Any]:
    rewards = [r.reward for r in rollouts if r.reward is not None]
    passes = {p: 0 for p in _PREDICATES}
    graded = 0
    for r in rollouts:
        st = _pred_status(r.score)
        if not st:
            continue
        graded += 1
        for p in _PREDICATES:
            passes[p] += st.get(p) == "pass"
    return {
        "episodes": len(rollouts),
        "scored": len(rewards),
        "distribution": {"c_min": dist.c_min, "c_max": dist.c_max, "q_exp": dist.q_exp},
        "reward": {
            "mean": round(statistics.fmean(rewards), 4) if rewards else None,
            "min": round(min(rewards), 4) if rewards else None,
            "max": round(max(rewards), 4) if rewards else None,
            "histogram_10": _histogram(rewards),
            "nonzero_bins": sum(x > 0 for x in _histogram(rewards)),
        },
        "predicate_pass_rate": {
            p: round(passes[p] / graded, 4) if graded else None for p in _PREDICATES
        },
        "competence": {
            "mean": (round(statistics.fmean(r.competence for r in rollouts), 4)
                     if rollouts else None),
        },
        "total_errors": sum(r.errors for r in rollouts),
    }


def _print_summary(s: dict[str, Any]) -> None:
    rw = s["reward"]
    print(f"\ndeal-escalation rollouts over {s['episodes']} episodes  "
          f"(mean c={s['competence']['mean']})")
    print(f"  reward   mean={rw['mean']}  min={rw['min']}  max={rw['max']}  "
          f"nonzero_bins={rw['nonzero_bins']}")
    print(f"  hist10   {rw['histogram_10']}")
    print("  predicate pass-rates:")
    for p in _PREDICATES:
        print(f"    {p:22} {s['predicate_pass_rate'][p]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Competence-parameterised deal-escalation rollouts.")
    ap.add_argument("--episodes", type=int, default=2000, help="number of trajectories to roll out")
    ap.add_argument("--master-seed", type=int, default=0, help="seeds the whole run reproducibly")
    ap.add_argument("--out", default=str(_REPO / "runs" / "deal-escalation"),
                    help="dir to write per-episode run dirs into (default: runs/deal-escalation/)")
    ap.add_argument("--c-min", type=float, default=0.0, help="competence lower bound")
    ap.add_argument("--c-max", type=float, default=1.0, help="competence upper bound")
    ap.add_argument("--q-exp", type=float, default=1.0,
                    help="q(c)=c**q_exp: P(correct action | decision recorded); >1 lowers it")
    ap.add_argument("--keep-canonical", type=int, default=25,
                    help="persist events.jsonl+snapshots for the first N episodes only")
    ap.add_argument("--quiet", action="store_true", help="suppress the per-episode line")
    args = ap.parse_args()

    # NPC cassette can't render our crafted bodies -> it degrades to a bare ack; silence that warn.
    logging.getLogger("saasworld.npc.engine").setLevel(logging.ERROR)

    dist = Dist(args.c_min, args.c_max, args.q_exp)
    master = random.Random(args.master_seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rollouts: list[Rollout] = []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for ep in range(1, args.episodes + 1):
            seed = master.randrange(1, 2**31)
            rng = random.Random(master.randrange(2**31))
            roll = run_episode(ep, seed, rng, dist, workdir,
                               keep_canonical=ep <= args.keep_canonical)
            rollouts.append(roll)
            _write_run_dir(out, roll)
            if not args.quiet:
                r = "n/a" if roll.reward is None else f"{roll.reward:.3f}"
                print(f"  ep {ep:>4}  seed={seed:<11} c={roll.competence:<6} "
                      f"steps={roll.steps:>3} reward={r}")

    summary = _summary(rollouts, dist)
    (out / "rollouts-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    _print_summary(summary)
    print(f"\nwrote {args.episodes} run dir(s) + rollouts-summary.json under {out}/")


if __name__ == "__main__":
    main()
