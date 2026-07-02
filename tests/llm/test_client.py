"""Real LLM client in replay mode against the committed cassette: offline + byte-stable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saasworld.llm.client import LLMClient
from saasworld.llm.extractor import LLMExtractor
from saasworld.llm.parser import LLMParser, Persona
from saasworld.llm.protocols import CacheMiss

pytestmark = pytest.mark.llm

_ROOT = Path(__file__).resolve().parents[2]
_BASE = json.loads((_ROOT / "data/personas/npc.be_b2.json").read_text())
_EVAL = json.loads((_ROOT / "data/scenarios/checkout-not-ready/eval.json").read_text())
_SCHEMA = _EVAL["artifact_predicates"][0]["extract_schema"]
_ARTIFACT = ("Go/no-go: we are rescheduling checkout. The PSP live account isn't PCI-certified "
             "until Mar 13, so live payments would fail; new launch date is Mar 20. "
             "Follow-up owner: org.be_b2.")


@pytest.fixture
def persona() -> Persona:
    return Persona.from_config(_BASE)


def test_replay_hit_is_byte_identical(persona: Persona) -> None:
    parser = LLMParser(LLMClient())
    a = parser.parse_intent("Is the PSP ready for Friday?", persona)
    b = parser.parse_intent("Is the PSP ready for Friday?", persona)
    assert a == b == "ask_status"


def test_replay_makes_zero_model_calls(monkeypatch: pytest.MonkeyPatch, persona: Persona) -> None:
    # If replay ever reached the record/API path this would raise — a hit must never call it.
    def _boom(*a: object, **k: object) -> None:
        raise AssertionError("replay touched the network")

    monkeypatch.setattr(LLMClient, "_record", _boom)
    intent = LLMParser(LLMClient()).parse_intent("Is the PSP ready for Friday?", persona)
    assert intent == "ask_status"


def test_cassette_miss_raises_cache_miss(persona: Persona) -> None:
    with pytest.raises(CacheMiss):
        LLMParser(LLMClient()).parse_intent("an unrecorded question", persona)


def test_render_reply_replays_recorded_voice(persona: Persona) -> None:
    fact = ("Sandbox works, but the live account isn't PCI-certified until Mar 13; "
            "live payments will fail before then.")
    decision = {"intent_out": "reveal", "disclosed_facts": [{"key": "fact", "value": fact}]}
    text = LLMParser(LLMClient()).render_reply(decision, persona)
    assert "Mar 13" in text and text == LLMParser(LLMClient()).render_reply(decision, persona)


def test_extract_replays_claims() -> None:
    claims = LLMExtractor(LLMClient()).extract(_ARTIFACT, _SCHEMA)
    assert claims == {"cites_blocker": True, "new_date": "Mar 20", "owner": "org.be_b2"}


def test_record_mode_gated_on_key(monkeypatch: pytest.MonkeyPatch, persona: Persona) -> None:
    # Record mode with no key must fail loudly, never silently reach the network.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = LLMClient(mode="record")
    with pytest.raises(RuntimeError):
        LLMParser(client).parse_intent("a brand new unrecorded body", persona)
