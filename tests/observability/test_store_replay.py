"""Record + replay: the persisted log round-trips byte-exactly with zero model calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saasworld.trajectory.replay import read_records, replay, state_at

from .conftest import SCRIPT, ForbiddenLLM, make_manifest, run_episode

pytestmark = pytest.mark.observability


def test_manifest_persisted_with_provenance(episode: tuple[str, Path]) -> None:
    run_id, base_dir = episode
    manifest = json.loads((base_dir / run_id / "manifest.json").read_text())
    # both hash roles present; comparability key is (instance_hash, action_space_version)
    assert (manifest["instance_hash"], manifest["action_space_version"]) == ("inst-abc", "v1")
    assert manifest["dataset_version"] == "ds-777"  # integrity only, not the comparability key
    assert manifest["llm_models"] == {
        "npc_parser": "claude-sonnet-5",
        "evaluator": "claude-sonnet-5",
    }


def test_manifest_records_caller_llm_models_override(tmp_path: Path) -> None:
    manifest = make_manifest(
        "run-llm", llm_models={"npc_parser": "claude-opus-9", "evaluator": "claude-sonnet-5"}
    )
    run_id = run_episode(tmp_path / "runs", manifest)
    written = json.loads((tmp_path / "runs" / run_id / "manifest.json").read_text())
    assert written["llm_models"]["npc_parser"] == "claude-opus-9"  # recorded verbatim, not computed


def test_trajectory_is_append_only_canonical(episode: tuple[str, Path]) -> None:
    run_id, base_dir = episode
    records = read_records(run_id, base_dir)
    assert [r["seq"] for r in records] == sorted(r["seq"] for r in records)  # append == seq order
    assert len(records) == len(SCRIPT)
    assert records[0]["run_id"] == run_id
    assert records[0]["delta"] is not None and records[0]["caused_by"] is None


def test_score_written_on_close(episode: tuple[str, Path]) -> None:
    run_id, base_dir = episode
    score = json.loads((base_dir / run_id / "score.json").read_text())
    assert score["total"] == 0.8


def test_replay_is_byte_identical_zero_calls(episode: tuple[str, Path]) -> None:
    run_id, base_dir = episode
    raw = (base_dir / run_id / "trajectory.jsonl").read_text()
    result = replay(run_id, base_dir, llm=ForbiddenLLM())
    assert result.event_log == raw  # re-serialized log == the bytes on disk
    assert result.model_calls == 0
    # final state reflects the last event (npc reply appended to the channel log)
    assert result.final_state["chat"]["checkout"]["log"] == ["status?", "on it"]


def test_state_at_equals_snapshot_plus_deltas(episode: tuple[str, Path]) -> None:
    run_id, base_dir = episode
    # before the update at t=30 the task is still 'todo'; after, 'in_progress'
    assert state_at(run_id, 1, base_dir).read("tasks.t1.status") == "todo"
    assert state_at(run_id, 4, base_dir).read("tasks.t1.status") == "in_progress"
    assert state_at(run_id, 3, base_dir).read("blockers.b1.surfaced") is True


def test_replay_twice_is_stable(episode: tuple[str, Path]) -> None:
    run_id, base_dir = episode
    a, b = replay(run_id, base_dir), replay(run_id, base_dir)
    assert a.event_log == b.event_log and a.final_state == b.final_state
