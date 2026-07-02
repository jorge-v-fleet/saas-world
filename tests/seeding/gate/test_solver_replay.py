"""Prove the solver's LLM seam is replay-only: full score, zero live calls, no API key.

A reference solver *may* drive discovery through the NPC parser; when it does, the parser goes
through the LLM record/replay cache in replay mode against a committed cassette. This asserts the
whole path runs with the key unset and that an unseen request is a hard miss, never a live call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from saasworld.engine.gate import run_pipeline
from saasworld.engine.solvers import competent_pm
from saasworld.engine.substrate import Substrate
from saasworld.llm.client import LLMClient
from saasworld.llm.parser import LLMParser, Persona
from saasworld.llm.protocols import CacheMiss

pytestmark = pytest.mark.seeding

_CASSETTE = Path(__file__).resolve().parents[2] / "cassettes" / "seeding.jsonl"


def _replay_parser() -> LLMParser:
    return LLMParser(LLMClient(mode="replay", cassette=_CASSETTE))


def test_llm_discovery_reaches_full_score_offline(
    template: dict[str, Any], substrate: Substrate, golden_seed: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    factmap, eval_json = run_pipeline(template, golden_seed, substrate)
    assert competent_pm(factmap, eval_json, parser=_replay_parser()) == pytest.approx(1.0)


def test_unseen_request_is_a_hard_miss_not_a_live_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    parser = _replay_parser()
    persona = Persona(id="npc.nobody", version="0", voice="x", allowed_intents=["greet"])
    with pytest.raises(CacheMiss):
        parser.parse_intent("a request never recorded in the cassette", persona)
