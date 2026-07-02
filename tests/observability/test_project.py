"""POV projection: pure, scoped views for agent / npc / operator / grader at any sim-time."""

from __future__ import annotations

from pathlib import Path

import pytest

from saasworld.trajectory.project import project

pytestmark = pytest.mark.observability

Scopes = dict[str, dict[str, list[str]]]


def test_operator_sees_full_log(episode: tuple[str, Path], scopes: Scopes) -> None:
    run_id, base_dir = episode
    view = project(run_id, "operator", at=60, base_dir=base_dir)
    assert len(view.events) == 5  # every event, unscoped
    assert view.state["blockers"]["b1"]["surfaced"] is True


def test_agent_pov_excludes_out_of_scope_paths(episode: tuple[str, Path], scopes: Scopes) -> None:
    run_id, base_dir = episode
    view = project(run_id, "agent", at=60, scopes=scopes, base_dir=base_dir)
    assert "tasks" in view.state and "blockers" not in view.state  # blockers out of agent scope
    assert all(e["actor"] != "system" for e in view.events)  # the reveal event is not visible


def test_pov_respects_at_timestamp(episode: tuple[str, Path], scopes: Scopes) -> None:
    run_id, base_dir = episode
    early = project(run_id, "agent", at=0, scopes=scopes, base_dir=base_dir)
    assert early.state["tasks"]["t1"]["status"] == "todo"  # before the t=30 update
    later = project(run_id, "agent", at=30, scopes=scopes, base_dir=base_dir)
    assert later.state["tasks"]["t1"]["status"] == "in_progress"


def test_npc_pov_shows_scoped_view(episode: tuple[str, Path], scopes: Scopes) -> None:
    run_id, base_dir = episode
    view = project(run_id, "npc.fe_a1", at=60, scopes=scopes, base_dir=base_dir)
    assert set(view.state) == {"chat"}  # only its scoped partition
    assert any(e["actor"] == "npc.fe_a1" for e in view.events)


def test_grader_pov_surfaces_factview_and_score(episode: tuple[str, Path], scopes: Scopes) -> None:
    run_id, base_dir = episode
    view = project(run_id, "grader", at=60, scopes=scopes, base_dir=base_dir)
    assert set(view.state) == {"tasks", "blockers"}  # exactly the eval fact-view
    assert view.extras["score"]["total"] == 0.8  # score derivation attached


def test_projection_is_pure(episode: tuple[str, Path], scopes: Scopes) -> None:
    run_id, base_dir = episode
    a = project(run_id, "agent", at=60, scopes=scopes, base_dir=base_dir)
    b = project(run_id, "agent", at=60, scopes=scopes, base_dir=base_dir)
    assert a == b
