"""Gated-completion timeline event: system effects apply only when a state precondition holds.

Mirrors the NPC reveal gate's anti-gaming property — a completion flips only if the agent did the
real work (here: booked the matching validation), and the flipped field is system-only.
"""

from __future__ import annotations

import pytest

from saasworld.kernel import Kernel
from saasworld.scenario.loader import _system_effect, _timeline_payload, offset_to_minutes
from saasworld.state.store import WorldState

pytestmark = pytest.mark.scenario

_GATE = {"exists": "calendar[?about=='f1.validation']"}
_EFFECT = [{"op": "set", "path": "tasks.f1.validated", "value": True}]
_AT = "D4T15:00"


def _kernel(initial: dict) -> Kernel:
    k = Kernel(WorldState(initial))
    k.register("system_effect", _system_effect)  # real handler the loader wires in
    return k


def _schedule(k: Kernel, entry: dict) -> None:
    k.schedule(offset_to_minutes(entry["at"]), "system", entry["type"], _timeline_payload(entry))


def test_effect_applies_when_gate_satisfied() -> None:
    k = _kernel({"tasks": {"f1": {"validated": False}},
                 "calendar": [{"id": "m1", "about": "f1.validation"}]})
    _schedule(k, {"id": "ev.v", "at": _AT, "type": "system_effect",
                  "gated_on": _GATE, "system_effect": _EFFECT})
    k.advance_until(offset_to_minutes(_AT))
    assert k.state.read("tasks.f1.validated") is True


def test_effect_skipped_when_gate_unsatisfied() -> None:
    k = _kernel({"tasks": {"f1": {"validated": False}}, "calendar": []})
    _schedule(k, {"id": "ev.v", "at": _AT, "type": "system_effect",
                  "gated_on": _GATE, "system_effect": _EFFECT})
    k.advance_until(offset_to_minutes(_AT))
    assert k.state.read("tasks.f1.validated") is False


def test_ungated_effect_always_applies() -> None:
    k = _kernel({"tasks": {"f1": {"validated": False}}})
    _schedule(k, {"id": "ev.v", "at": _AT, "type": "system_effect", "system_effect": _EFFECT})
    k.advance_until(offset_to_minutes(_AT))
    assert k.state.read("tasks.f1.validated") is True


def test_gated_field_is_system_only() -> None:
    # The completion field is a per-instance denied path: only source="system" may flip it,
    # so the agent can never fake the effect the gate protects.
    state = WorldState({"tasks": {"f1": {"validated": False}}}, denied_paths=["tasks.*.validated"])
    state.apply(_EFFECT, source="system")  # the gated-completion path
    assert state.read("tasks.f1.validated") is True
    with pytest.raises(PermissionError):
        state.apply(_EFFECT, source="org.pm_a")  # an agent-sourced write is refused
