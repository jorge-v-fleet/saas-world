"""NPC Engine — Kernel handler for reactive coworkers.

`npc_reply` (scheduled at now + the persona's response_delay) is the single reactive event: it
parses the free-text body into one allowed intent, runs the UNCHANGED decision core (which owns
every reveal/mutation, system-sourced), renders the core-chosen reply in the persona's voice, and
appends it. The parser can request an intent; only the core can grant a reveal.
"""

from __future__ import annotations

import logging
from typing import Any

from ..eval.predicates import holds
from ..events import Event
from ..kernel import Kernel
from ..llm.parser import LLMParser, Persona
from ..llm.protocols import CacheMiss
from ..state.store import WorldState
from .decision import Decision, decide

_DEFAULT_DELAY_MIN = 60
_FALLBACK_ACK = "Ack."  # deterministic, LLM-free reply used when the parser fails
_AGENT = "org.pm_a"  # the single PM under test — proactive outreach targets the agent
_PROACTIVE_CAP = 5  # default per-NPC ceiling on autonomous messages over the horizon
_MIN_PER_DAY = 24 * 60

logger = logging.getLogger(__name__)

# In replay (the default, key-free) mode a novel free-text message isn't in the cassette, so the
# parser fails on nearly every message a real agent sends — expected, not a fault. Log the first
# such degradation per process at INFO (with the fix hint), the rest at DEBUG, so served output
# stays clean instead of flooding with tracebacks. A genuinely unexpected error stays loud.
_notified = False


def _log_expected(msg: str, *args: Any) -> None:
    global _notified
    if not _notified:
        _notified = True
        logger.info(msg + " — set SAASWORLD_LLM_MODE=record to capture novel messages", *args)
    else:
        logger.debug(msg, *args)


class NPCEngine:
    """Holds active NPC runtime configs (keyed by org id) and drives their reactions."""

    def __init__(self, parser: Any | None = None) -> None:
        self.npcs: dict[str, dict[str, Any]] = {}
        self._parser = parser
        self._proactive_count: dict[str, int] = {}  # per-NPC autonomous-message tally

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
        kernel.register("npc_wakeup", self._npc_wakeup)
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
        except (CacheMiss, ValueError) as exc:
            # Expected: a novel body isn't in the cassette (CacheMiss) or the model returned an
            # out-of-enum intent (ValueError). Fail CLOSED — the core is bypassed so no gated fact
            # can leak on an unclassifiable message — and keep the sim live with a bare ack.
            _log_expected("npc_reply: unclassified message from %s (seq=%s) [%s]; bare ack",
                          payload.get("npc"), event.seq, type(exc).__name__)
            decision = Decision(reply={"kind": "ack", "refs": [], "fields": {}})
        except Exception:
            # Unexpected (e.g. a real API error in record mode): keep it loud with a traceback.
            logger.warning("npc_reply: parse failed unexpectedly for %s (seq=%s); degrading to "
                           "bare ack", payload.get("npc"), event.seq, exc_info=True)
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

    def _npc_wakeup(self, kernel: Kernel, event: Event) -> list[dict[str, Any]]:
        """Autonomous replan: if the persona's goal is unmet, emit a bounded proactive message,
        then reschedule the next tick. Opt-in per scenario; DEFAULT OFF (loader schedules none)."""
        payload = event.payload
        org_id = payload["npc"]
        npc = self.npcs.get(org_id)
        if npc is None:
            return []
        cadence = npc.get("behavior", {}).get("wakeup_cadence", {})
        every = int(cadence.get("every_sim_hours", 0)) * 60
        if every <= 0:
            return []
        horizon = int(payload.get("horizon", 0))
        cap = int(cadence.get("max_proactive", _PROACTIVE_CAP))
        now = event.sim_time

        # Outside work hours: don't act; slide the tick to the next work-hours start.
        start = _next_work_start(npc, now)
        if start > now:
            if start <= horizon:
                kernel.schedule(start, org_id, "npc_wakeup", payload, caused_by=event.seq)
            return []

        # Goal already satisfied by world state (read via view_scope) -> stop chasing.
        view = WorldState(kernel.state.view(npc.get("view_scope", {})))
        if _goal_satisfied(cadence, view):
            return []

        applied: list[dict[str, Any]] = []
        if self._proactive_count.get(org_id, 0) < cap:
            msg = _proactive_message(npc, org_id, cadence, event.seq)
            kernel.state.apply([msg], source=org_id)  # normal messages path, NPC-sourced
            applied.append(msg)
            self._proactive_count[org_id] = self._proactive_count.get(org_id, 0) + 1

        nxt = now + every
        if self._proactive_count.get(org_id, 0) < cap and nxt <= horizon:
            kernel.schedule(nxt, org_id, "npc_wakeup", payload, caused_by=event.seq)
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
        except CacheMiss as exc:
            # Expected in replay: this reply shape isn't in the cassette. The structured reply
            # (kind/refs and any already-applied reveal) still stands; only the prose degrades.
            _log_expected("npc_reply: unrendered reply for %s [%s]; bare ack text",
                          persona.id, type(exc).__name__)
            text = _FALLBACK_ACK
        except Exception:
            # Unexpected error while rendering: keep it loud with a traceback.
            logger.warning("npc_reply: render failed unexpectedly for %s; using bare ack text",
                           persona.id, exc_info=True)
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


def _hhmm(v: str) -> int:
    h, _, m = v.partition(":")
    return int(h) * 60 + int(m)


def _next_work_start(npc: dict[str, Any], now: int) -> int:
    """`now` if within work hours; else the next work-hours start (later today or tomorrow)."""
    wh = npc.get("behavior", {}).get("work_hours")
    if not wh:
        return now  # always-on persona
    start, end = _hhmm(wh["start"]), _hhmm(wh["end"])
    tod = now % _MIN_PER_DAY
    day0 = now - tod
    if start <= tod < end:
        return now
    return day0 + start if tod < start else day0 + _MIN_PER_DAY + start


def _goal_satisfied(cadence: dict[str, Any], view: WorldState) -> bool:
    """Data-driven predicate over the NPC's scoped view. `satisfied_when` is an eval-assert spec
    (reuses `holds`); absent -> never satisfied, so the NPC keeps chasing (bounded by the cap)."""
    spec = cadence.get("satisfied_when")
    return holds(spec, state=view) if spec else False


def _proactive_message(
    npc: dict[str, Any], org_id: str, cadence: dict[str, Any], seq: int
) -> dict[str, Any]:
    """A deterministic, LLM-free outreach delta toward the agent (seeded off event seq)."""
    name = npc.get("identity", {}).get("name", org_id)
    intent = cadence.get("intent", "ask_status")
    about = cadence.get("about")
    return {
        "op": "append",
        "path": "messages",
        "value": {
            "from": org_id, "to": _AGENT, "intent": intent, "about": about,
            "kind": "proactive", "proactive_seq": seq,
            "note": f"{name}: following up — {intent.replace('_', ' ')}",
        },
    }
