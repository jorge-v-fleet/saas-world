"""Static per-intent template renderer: structured reply -> text in the persona's voice.

The decision core emits a structured `reply`; this turns it into a message body. A voice renderer
can replace this table without touching the decision core's contract.
"""

from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, str] = {
    "reveal": "{name}: heads up — {fact}",
    "status": "{name}: {status}.",
    "ack": "{name}: ack.",
}


def render(reply: dict[str, Any], npc: dict[str, Any]) -> str:
    """Render a structured reply to text; unknown kinds fall back to a bare acknowledgement."""
    name = npc.get("identity", {}).get("name", npc.get("org_ref", "?"))
    template = TEMPLATES.get(reply.get("kind", "ack"), TEMPLATES["ack"])
    return template.format(name=name, **reply.get("fields", {}))
