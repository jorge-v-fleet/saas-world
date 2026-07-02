"""Reactive rule-based decision core: pure function of (intent, scoped view, npc config).

Consumes a structured `intent` (an upstream parser can map free text to it, unchanged contract).
Emits a structured `reply`, reveal deltas, and delivery follow-ups. No wall-clock, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_DEFAULT_DELAY_MIN = 60


@dataclass
class Decision:
    reply: dict[str, Any] | None
    deltas: list[dict[str, Any]] = field(default_factory=list)
    follow_ups: list[dict[str, Any]] = field(default_factory=list)


def _mentioned(args: dict[str, Any]) -> set[str]:
    """Topics the incoming message points at: structured `refs` plus an optional `about`."""
    topics = set(args.get("refs") or [])
    if args.get("about"):
        topics.add(args["about"])
    return topics


def _gate_satisfied(item: dict[str, Any], intent: str, args: dict[str, Any]) -> bool:
    """Does this message unlock the gated fact? intent + topic must match, then the gate."""
    reveal_when = item.get("reveal_when", {})
    if intent != reveal_when.get("intent"):
        return False
    topics = reveal_when.get("about") or []
    if topics and not (_mentioned(args) & set(topics)):
        return False
    gate = item.get("gate", "ask_direct")
    if gate == "needs_help_offer":
        return bool(args.get("help_offered"))
    if gate == "needs_rapport":
        return bool(args.get("rapport"))
    return True  # ask_direct


def _response_delay(npc: dict[str, Any]) -> int:
    """Deterministic delay = the persona's modal response time (no sampling)."""
    delay = npc.get("behavior", {}).get("response_delay", {})
    return int(delay.get("mode_min", _DEFAULT_DELAY_MIN))


def decide(
    npc: dict[str, Any], intent: str, args: dict[str, Any], view: dict[str, Any]
) -> Decision:
    """Map an incoming intent to a reveal (if the gate is satisfied) plus a reply to deliver."""
    revealed: dict[str, Any] | None = None
    deltas: list[dict[str, Any]] = []
    for item in npc.get("knowledge_scope", []):
        if _gate_satisfied(item, intent, args):
            blocker = item.get("links_blocker")
            if blocker:
                deltas.append({"op": "set", "path": f"blockers.{blocker}.surfaced", "value": True})
            revealed = item
            break

    reply: dict[str, Any] | None = None
    if revealed is not None:
        blocker = revealed.get("links_blocker")
        reply = {
            "kind": "reveal",
            "refs": [blocker] if blocker else [],
            "fields": {"fact": revealed.get("fact", "")},
        }
    elif intent in npc.get("allowed_intents", []):
        reply = {"kind": "ack", "refs": [], "fields": {}}

    follow_ups: list[dict[str, Any]] = []
    if reply is not None:
        follow_ups = [{"kind": "deliver_reply", "delay": _response_delay(npc)}]
    return Decision(reply=reply, deltas=deltas, follow_ups=follow_ups)
