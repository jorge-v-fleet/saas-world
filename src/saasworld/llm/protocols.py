"""LLMClientProto (injection seam) + FakeLLM (canned, for isolated unit tests).

The parser/extractor depend on `LLMClientProto`, exactly like the Kernel depends on `StateWriter`.
The real client caches + replays; FakeLLM stands in with canned outputs so neighbours test offline.
"""

from __future__ import annotations

from typing import Any, Protocol


class CacheMiss(RuntimeError):
    """Replay mode: no recorded output for this canonical key (never falls back to a live call)."""


class LLMClientProto(Protocol):
    def call(
        self,
        *,
        kind: str,
        model: str,
        system: str,
        schema: Any,
        messages: list[dict[str, Any]],
        params: dict[str, Any],
        persona: dict[str, str] | None = None,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


def _content(messages: list[dict[str, Any]]) -> str:
    """Concatenate user message contents (the inert data body/artifact)."""
    return "\n".join(str(m.get("content", "")) for m in messages)


class FakeLLM:
    """Canned client for unit isolation. Matches parse intents by substring; render/claims fixed."""

    def __init__(
        self,
        *,
        intents: dict[str, str] | None = None,
        reply: str = "",
        claims: dict[str, Any] | None = None,
    ) -> None:
        self.intents = intents or {}
        self.reply = reply
        self.claims = claims or {}
        self.calls: list[dict[str, Any]] = []

    def call(
        self,
        *,
        kind: str,
        model: str,
        system: str,
        schema: Any,
        messages: list[dict[str, Any]],
        params: dict[str, Any],
        persona: dict[str, str] | None = None,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"kind": kind, "messages": messages, "persona": persona})
        if kind == "parse_intent":
            content = _content(messages)
            for needle, intent in self.intents.items():
                if needle == "*" or needle in content:
                    return {"intent": intent}
            return {"intent": self.intents.get("*", "")}
        if kind == "render_reply":
            return {"text": self.reply}
        if kind == "extract":
            return dict(self.claims)
        raise ValueError(f"unknown kind {kind!r}")
