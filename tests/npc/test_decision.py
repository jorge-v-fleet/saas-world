"""NPC decision core + engine handlers: reveal gating, reply scheduling, system-sourced reveals."""

from __future__ import annotations

from typing import Any

import pytest

from saasworld.npc.decision import decide
from saasworld.npc.engine import NPCEngine
from saasworld.npc.reply import render

pytestmark = pytest.mark.npc


def _npc(gate: str = "ask_direct", **behavior: Any) -> dict[str, Any]:
    return {
        "org_ref": "org.be_b2",
        "identity": {"name": "Priya Nair"},
        "allowed_intents": ["greet", "ask_status", "offer_help"],
        "behavior": {"response_delay": {"mode_min": behavior.get("delay", 90)}},
        "knowledge_scope": [
            {
                "id": "know.psp_cert",
                "links_blocker": "blocker.psp_cert",
                "fact": "PSP not certified until after launch.",
                "gate": gate,
                "reveal_when": {"intent": "ask_status",
                                "about": ["payments", "task.psp_integration"]},
            }
        ],
    }


def _ask(about: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"to": "org.be_b2", "body": "?", "refs": about or ["task.psp_integration"], **extra}


# --- decision core -----------------------------------------------------------


def test_ask_direct_gate_reveals_blocker():
    d = decide(_npc(), "ask_status", _ask(), {})
    assert d.deltas == [
        {"op": "set", "path": "blockers.blocker.psp_cert.surfaced", "value": True}
    ]
    assert d.reply["kind"] == "reveal"
    assert d.reply["refs"] == ["blocker.psp_cert"]


def test_wrong_topic_does_not_reveal():
    d = decide(_npc(), "ask_status", _ask(about=["task.checkout_ui"]), {})
    assert d.deltas == []
    assert d.reply["kind"] == "ack"  # still replies, but no reveal


def test_wrong_intent_does_not_reveal():
    d = decide(_npc(), "greet", _ask(), {})
    assert d.deltas == []
    assert d.reply["kind"] == "ack"


@pytest.mark.parametrize(
    "gate, args, revealed",
    [
        ("ask_direct", {}, True),
        ("needs_help_offer", {}, False),
        ("needs_help_offer", {"help_offered": True}, True),
        ("needs_rapport", {}, False),
        ("needs_rapport", {"rapport": True}, True),
    ],
)
def test_gate_table(gate, args, revealed):
    d = decide(_npc(gate=gate), "ask_status", _ask(**args), {})
    assert bool(d.deltas) is revealed


def test_reply_scheduled_at_response_delay():
    d = decide(_npc(delay=42), "ask_status", _ask(), {})
    assert d.follow_ups == [{"kind": "deliver_reply", "delay": 42}]


def test_unknown_intent_yields_no_reply():
    d = decide(_npc(), "unknown_intent", _ask(), {})
    assert d.reply is None and d.follow_ups == []


def test_decision_is_deterministic():
    a = decide(_npc(), "ask_status", _ask(), {})
    b = decide(_npc(), "ask_status", _ask(), {})
    assert (a.reply, a.deltas, a.follow_ups) == (b.reply, b.deltas, b.follow_ups)


def test_render_uses_persona_voice():
    reply = {"kind": "reveal", "refs": [], "fields": {"fact": "cert pending"}}
    assert render(reply, _npc()) == "Priya Nair: heads up — cert pending"


# --- engine over a fake kernel (parser injected for isolation) ---------------


class _FakeKernel:
    def __init__(self) -> None:
        self.applied: list[tuple[list[dict[str, Any]], str]] = []
        self.state = self

    def snapshot(self) -> dict[str, Any]:
        return {}

    def apply(self, deltas: list[dict[str, Any]], source: str) -> None:
        self.applied.append((deltas, source))


def _engine(intent: str = "ask_status", reply: str = "Priya: cert pending") -> NPCEngine:
    from saasworld.llm.parser import LLMParser
    from saasworld.llm.protocols import FakeLLM

    engine = NPCEngine(parser=LLMParser(FakeLLM(intents={"*": intent}, reply=reply)))
    engine.register_npc(_npc())
    return engine


def _reply_event(body: str = "?", about: list[str] | None = None):
    from saasworld.events import Event

    payload = {"npc": "org.be_b2", "body": body, "args": _ask(about=about), "sender": "org.pm_a"}
    return Event(1, 0, "org.be_b2", "npc_reply", payload)


def test_engine_applies_reveal_system_sourced():
    k = _FakeKernel()
    _engine()._npc_reply(k, _reply_event())
    assert k.applied[0][1] == "system"  # reveal is system-sourced
    assert k.applied[0][0][0]["path"] == "blockers.blocker.psp_cert.surfaced"


def test_engine_appends_voiced_reply_from_npc():
    k = _FakeKernel()
    _engine(reply="Priya: heads up")._npc_reply(k, _reply_event())
    deltas, source = k.applied[-1]
    assert source == "org.be_b2" and deltas[0]["path"] == "messages"
    assert deltas[0]["value"]["from"] == "org.be_b2" and deltas[0]["value"]["to"] == "org.pm_a"
    assert deltas[0]["value"]["body"] == "Priya: heads up"
    assert deltas[0]["value"]["refs"] == ["blocker.psp_cert"]


def test_engine_acks_without_reveal_on_wrong_topic():
    k = _FakeKernel()
    _engine(reply="Ack.")._npc_reply(k, _reply_event(about=["task.checkout_ui"]))
    assert len(k.applied) == 1  # no reveal delta, only the ack message
    assert k.applied[0][0][0]["value"]["kind"] == "ack"


def test_engine_ignores_unknown_npc():
    engine = NPCEngine(parser=_engine().parser)
    engine.npcs.clear()
    k = _FakeKernel()
    engine._npc_reply(k, _reply_event())
    assert k.applied == []
