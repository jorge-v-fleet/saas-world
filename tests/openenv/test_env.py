"""OpenEnv-shaped SDK: env reset/step/terminal-reward, and the HTTP client/server round-trip.

Drives the same discover -> decide -> inform loop the README documents and asserts the terminal
reward equals the deterministic Evaluator's final (score parity with `saasworld run-eval`).
"""

from __future__ import annotations

from typing import Any

import pytest

from saasworld.openenv import SaasWorldAction, SaasWorldEnvironment, create_env_app
from saasworld.openenv.types import SaasWorldObservation, State, StepResult

pytestmark = pytest.mark.openenv

# The competent solution: ask the holder (exact recorded body -> real reveal), reschedule, tell CTO.
DISCOVER = SaasWorldAction("send_message", {
    "to": "org.be_b2", "body": "Is the PSP ready for Friday?", "refs": ["task.psp_integration"]})
DECIDE = SaasWorldAction("record_decision", {"about": "proj.checkout", "type": "gonogo",
                         "action": "reschedule", "new_date": "D8T17:00", "owner": "org.be_b2"})
INFORM = SaasWorldAction("send_message", {
    "to": "org.cto", "body": "Checkout slips: PSP cert is the blocker.",
    "refs": ["blocker.psp_cert"]})
WAIT = SaasWorldAction("wait", {"duration": 120})


def _drive(step: Any) -> Any:
    """Run the competent loop via a `step(action)` callable; return the terminal result
    (a SaasWorldObservation in-process, a StepResult over HTTP — both carry done/reward)."""
    step(DISCOVER)
    step(WAIT)                    # let Priya's reply fire -> blocker surfaces
    step(DECIDE)
    step(INFORM)
    return step(SaasWorldAction("wait", {"duration": 7000}))  # advance past the horizon -> done


# ---- in-process environment -----------------------------------------------------------------


def test_reset_seeds_world_and_is_not_terminal() -> None:
    env = SaasWorldEnvironment()
    obs = env.reset("checkout-not-ready")
    assert isinstance(obs, SaasWorldObservation)
    assert obs.done is False and obs.reward is None
    assert "proj" in obs.state["projects"]                 # seeded world is visible
    assert obs.metadata["scenario_id"] == "checkout-not-ready"
    assert obs.metadata["horizon"] == 6780                 # D5T17:00


def test_step_requires_reset() -> None:
    with pytest.raises(RuntimeError):
        SaasWorldEnvironment().step(DISCOVER)


def test_terminal_reward_matches_evaluator() -> None:
    env = SaasWorldEnvironment()
    env.reset("checkout-not-ready")
    final = _drive(env.step)  # in-process step() returns SaasWorldObservation directly
    assert final.done is True
    assert final.reward is not None and final.reward > 0.8   # discovered + acted + correct + told
    # the blocker was surfaced by the NPC (un-gameable field), proving discovery really happened
    assert final.state["blockers"]["blocker"]["psp_cert"]["surfaced"] is True
    # reward is the evaluator final, breakdown carried in metadata
    assert final.metadata["score"]["final"] == final.reward


def test_invalid_action_is_not_terminal_and_surfaces_error() -> None:
    env = SaasWorldEnvironment()
    env.reset("checkout-not-ready")
    obs = env.step(SaasWorldAction("record_decision", {"bogus": 1}))  # missing required args
    assert obs.done is False and obs.reward is None
    assert "error" in obs.metadata


def test_busy_run_scores_low() -> None:
    """Activity without the real work: reward stays ~0 — the anti-gaming property via the SDK."""
    env = SaasWorldEnvironment()
    env.reset("checkout-not-ready")
    env.step(SaasWorldAction("send_message", {"to": "chan.checkout", "body": "great work team"}))
    final = env.step(SaasWorldAction("wait", {"duration": 7000}))
    assert final.done is True and final.reward == 0.0
    assert final.metadata["outcome"] == "completed"  # reached the week's end, did nothing useful


def test_max_weeks_timeout_is_a_failure() -> None:
    """A budget shorter than the scenario's horizon force-closes as a timeout failure: reward 0.0
    and outcome='timeout', with the deterministic breakdown still attached for inspection."""
    env = SaasWorldEnvironment()
    reset = env.reset("checkout-not-ready", max_weeks=0.5)  # deadline 5040 < horizon 6780
    assert reset.metadata["deadline"] == 5040
    final = env.step(SaasWorldAction("wait", {"duration": 6000}))  # cross the deadline, not horizon
    assert final.done is True and final.reward == 0.0
    assert final.metadata["outcome"] == "timeout" and final.metadata["terminated"] == "max_weeks"
    assert "score" in final.metadata  # breakdown kept for inspection despite the floored reward


def test_slack_max_weeks_grades_normally() -> None:
    """A budget beyond the horizon is slack — the episode still completes and grades on merit."""
    env = SaasWorldEnvironment()
    env.reset("checkout-not-ready", max_weeks=2)  # deadline 20160 >> horizon
    final = _drive(env.step)
    assert final.done is True and final.reward is not None and final.reward > 0.8
    assert final.metadata["outcome"] == "completed"


# ---- HTTP client/server round-trip ----------------------------------------------------------


def test_http_roundtrip_parses_stepresult() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(create_env_app())

    def step(action: SaasWorldAction) -> StepResult:
        body = client.post("/step", json={"action": action.to_dict()}).json()
        return StepResult.from_dict(body)

    reset = StepResult.from_dict(
        client.post("/reset", json={"scenario": "checkout-not-ready"}).json())
    assert reset.done is False and reset.observation.state["projects"]

    final = _drive(step)
    assert final.done is True and final.reward is not None and final.reward > 0.8

    state = State.from_dict(client.get("/state").json())
    assert state.scenario_id == "checkout-not-ready" and state.step_count > 0
    assert client.get("/health").json() == {"status": "ok"}


def test_inspector_is_mounted_on_the_env_server(tmp_path: Any, monkeypatch: Any) -> None:
    """The unified server also hosts the trajectory inspector (SPA + read-only runs API)."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SAASWORLD_RUNS_DIR", str(tmp_path))  # empty runs dir -> zero runs
    client = TestClient(create_env_app())

    spa = client.get("/inspector")
    assert spa.status_code == 200 and "<title>" in spa.text
    runs = client.get("/inspector/api/runs").json()
    assert runs["count"] == 0 and runs["runs"] == []
    # env contract still lives on the same app
    assert client.get("/health").json() == {"status": "ok"}


def test_inspector_detail_inlines_llm_transcript(tmp_path: Any, monkeypatch: Any) -> None:
    """The run detail carries the LLM transcript (messages.json) inline; null when absent."""
    import json

    from fastapi.testclient import TestClient

    monkeypatch.setenv("SAASWORLD_RUNS_DIR", str(tmp_path))
    client = TestClient(create_env_app())

    with_msgs = tmp_path / "agent-demo"
    with_msgs.mkdir()
    (with_msgs / "manifest.json").write_text(json.dumps({"kind": "agent", "actions": 1}))
    (with_msgs / "trajectory.jsonl").write_text(
        json.dumps({"turn": 1, "verb": "send_message", "args": {"to": "org.cto"}}) + "\n"
    )
    (with_msgs / "messages.json").write_text(json.dumps([
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "t1", "name": "send_message", "input": {"to": "org.cto"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "{}"},
        ]},
    ]))

    detail = client.get("/inspector/api/runs/agent-demo").json()
    assert detail["has_messages"] is True
    assert isinstance(detail["messages"], list) and len(detail["messages"]) == 3

    no_msgs = tmp_path / "agent-bare"
    no_msgs.mkdir()
    (no_msgs / "manifest.json").write_text(json.dumps({"kind": "agent", "actions": 0}))
    bare = client.get("/inspector/api/runs/agent-bare").json()
    assert bare["has_messages"] is False and bare["messages"] is None
