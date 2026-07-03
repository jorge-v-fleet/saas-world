"""The competence-parameterised deal-escalation rollout generator: a small end-to-end batch.

Asserts the generator writes standard run dirs whose score.json comes from the real evaluator, that
the sample is non-degenerate (>1 distinct reward), and that every score is well-formed."""

from __future__ import annotations

import importlib.util
import json
import random
import sys
import tempfile
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deal_escalation_rollouts.py"
_spec = importlib.util.spec_from_file_location("deal_escalation_rollouts", _SCRIPT)
assert _spec and _spec.loader
der = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = der
_spec.loader.exec_module(der)


def test_small_batch_writes_wellformed_nondegenerate_runs(tmp_path):
    dist = der.Dist(c_min=0.0, c_max=1.0, q_exp=1.0)
    master = random.Random(0)
    out = tmp_path / "runs"
    out.mkdir()

    rewards: list[float] = []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for ep in range(1, 31):  # small + fast
            seed = master.randrange(1, 2**31)
            rng = random.Random(master.randrange(2**31))
            roll = der.run_episode(ep, seed, rng, dist, workdir, keep_canonical=ep <= 3)
            der._write_run_dir(out, roll)
            assert roll.reward is not None  # every episode crosses the horizon -> real score
            rewards.append(roll.reward)

    run_dirs = sorted(out.glob("rollout-*"))
    assert len(run_dirs) == 30

    for d in run_dirs:
        assert (d / "manifest.json").exists()
        assert (d / "trajectory.jsonl").exists()
        score = json.loads((d / "score.json").read_text())
        assert abs(score["weights_sum"] - 1.0) < 1e-9
        assert 0.0 <= score["final"] <= 1.0 + 1e-9
        preds = {p["id"]: p for cp in score["checkpoints"] for p in cp["predicates"]}
        assert set(preds) == set(der._PREDICATES)  # all six graded predicates present
        for p in preds.values():
            assert p["status"] in {"pass", "fail", "pending"}
            assert 0.0 <= p["credit"] <= 1.0

    assert len(set(rewards)) >= 2  # non-degenerate on the sample
