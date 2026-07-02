"""Persona fixtures for the NPC parser tier."""

from __future__ import annotations

import pytest

from saasworld.llm.parser import Persona


@pytest.fixture
def priya() -> Persona:
    return Persona.from_config({
        "id": "npc.be_b2",
        "voice": "Terse, precise, a little defensive when pressed.",
        "allowed_intents": ["greet", "ask_status", "ask_eta", "report_blocker", "acknowledge"],
    })
