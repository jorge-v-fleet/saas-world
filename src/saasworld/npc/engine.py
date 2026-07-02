"""NPC Engine — Kernel handler for reactive coworkers.

`npc_reply` (scheduled at now + the persona's response_delay) is the single reactive event: it
parses the free-text body into one allowed intent, runs the UNCHANGED decision core (which owns
every reveal/mutation, system-sourced), renders the core-chosen reply in the persona's voice, and
appends it. The parser can request an intent; only the core can grant a reveal.
"""

from __future__ import annotations

import logging
from typing import Any

from ..events import Event
from ..kernel import Kernel
from ..llm.parser import LLMParser, Persona
from .decision import Decision, decide

_DEFAULT_DELAY_MIN = 60
_FALLBACK_ACK = "Ack."  # deterministic, LLM-free reply used when the parser fails

logger = logging.getLogger(__name__)


class NPCEngine:
    """Holds active NPC runtime configs (keyed by org id) and drives their reactions."""

    def __init__(self, parser: Any | None = None) -> None:
        self.npcs: dict[str, dict[str, Any]] = {}
        self._parser = parser

    def register_npc(self, config: dict[str, Any]) -> None:
        """Register a runtime config (base persona ⊕ overlay), keyed by its structural org id."""
        self.npcs[config["org_ref"]] = config

    def is_registered(self, org_id: str | None) -> bool:
        return org_id in self.npcs

    def response_delay(self, org_id: str) -> int:
        """The persona's modal response time — when its reactive reply is scheduled."""
        npc = self.npcs.get(org_id, {})
        delay = npc.get("behavior", {}).get("response_delay", {})
        return int(delay.get("mode_min", _DEFAULT_DELAY_MIN))

    def attach(self, kernel: Kernel) -> None:
        kernel.register("npc_reply", self._npc_reply)
        kernel.npc_engine = self  # type: ignore[attr-defined]  # expose registry to send_message

    @property
    def parser(self) -> Any:
        """Lazily build the default replay parser; injected in tests for isolation."""
        if self._parser is None:
            from ..llm.client import LLMClient

            self._parser = LLMParser(LLMClient())
        return self._parser

    def _npc_reply(self, kernel: Kernel, event: Event) -> list[dict[str, Any]]:
        """Parse -> decision core (reveals now, system-sourced) -> render -> append reply."""
        payload = event.payload
        npc = self.npcs.get(payload["npc"])
        if npc is None:
            return []
        persona = Persona.from_config(npc)
        try:
            intent = self.parser.parse_intent(payload.get("body", ""), persona)
        except Exception:
            # Parser failed (cache miss / out-of-enum / API error): fail CLOSED — the core is
            # bypassed so no gated fact can leak on an unclassifiable message — but keep the sim
            # live with a fixed bare acknowledgement.
            logger.warning("npc_reply: parse failed for %s (seq=%s); degrading to bare ack",
                           payload.get("npc"), event.seq, exc_info=True)
            decision = Decision(reply={"kind": "ack", "refs": [], "fields": {}})
        else:
            decision = decide(npc, intent, payload.get("args", {}), kernel.state.snapshot())
        applied: list[dict[str, Any]] = []
        if decision.deltas:
            kernel.state.apply(decision.deltas, source="system")
            applied.extend(decision.deltas)
        msg = self._reply_delta(decision, persona, payload.get("sender"), event.actor)
        if msg is not None:
            kernel.state.apply([msg], source=event.actor)
            applied.append(msg)
        return applied

    def _reply_delta(
        self, decision: Decision, persona: Persona, to: str | None, actor: str
    ) -> dict[str, Any] | None:
        """Voice-render the core-chosen reply and shape it as a message append delta."""
        if decision.reply is None:
            return None
        disclosed = [{"key": k, "value": v} for k, v in decision.reply.get("fields", {}).items()]
        try:
            text = self.parser.render_reply(
                {"intent_out": decision.reply.get("kind"), "disclosed_facts": disclosed}, persona
            )
        except Exception:
            # Render failed: the structured reply (kind/refs and any already-applied reveal) still
            # stands; only the prose degrades to a fixed acknowledgement.
            logger.warning("npc_reply: render failed for %s; using bare ack text", persona.id,
                           exc_info=True)
            text = _FALLBACK_ACK
        return {
            "op": "append",
            "path": "messages",
            "value": {
                "from": actor,
                "to": to,
                "body": text,
                "kind": decision.reply.get("kind"),
                "refs": decision.reply.get("refs", []),
            },
        }
