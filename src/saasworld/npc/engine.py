"""NPC Engine — Kernel handler for reactive coworkers (rule-based, deterministic).

`npc_react` runs the decision core over the NPC's config, applies reveal deltas (`source="system"`,
the only writer allowed to flip a graded field) and schedules a `deliver_reply`. `deliver_reply`
appends the rendered reply to the recipient's inbox. Registered on the Kernel like any handler.
"""

from __future__ import annotations

from typing import Any

from ..events import Event
from ..kernel import Kernel
from .decision import decide
from .reply import render


class NPCEngine:
    """Holds active NPC runtime configs (keyed by org id) and drives their reactions."""

    def __init__(self) -> None:
        self.npcs: dict[str, dict[str, Any]] = {}

    def register_npc(self, config: dict[str, Any]) -> None:
        """Register a runtime config (base persona ⊕ overlay), keyed by its structural org id."""
        self.npcs[config["org_ref"]] = config

    def attach(self, kernel: Kernel) -> None:
        kernel.register("npc_react", self._npc_react)
        kernel.register("deliver_reply", self._deliver_reply)

    def _npc_react(self, kernel: Kernel, event: Event) -> list[dict[str, Any]]:
        """Trigger: decide, apply reveals now, schedule the reply at now + response_delay."""
        payload = event.payload
        npc = self.npcs.get(payload["npc"])
        if npc is None:
            return []
        decision = decide(npc, payload["intent"], payload.get("args", {}), kernel.state.snapshot())
        if decision.deltas:
            kernel.state.apply(decision.deltas, source="system")
        if decision.reply is not None:
            reply = {**decision.reply, "text": render(decision.reply, npc)}
            for fu in decision.follow_ups:
                kernel.schedule(
                    event.sim_time + fu["delay"],
                    payload["npc"],
                    "deliver_reply",
                    {"to": payload.get("sender"), "reply": reply},
                    caused_by=event.seq,
                )
        return decision.deltas

    def _deliver_reply(self, kernel: Kernel, event: Event) -> list[dict[str, Any]]:
        """Delivery: append the reply to the recipient's inbox."""
        payload = event.payload
        reply = payload["reply"]
        delta = {
            "op": "append",
            "path": "messages",
            "value": {
                "from": event.actor,
                "to": payload.get("to"),
                "body": reply.get("text", ""),
                "kind": reply.get("kind"),
                "refs": reply.get("refs", []),
            },
        }
        kernel.state.apply([delta], source=event.actor)
        return [delta]
