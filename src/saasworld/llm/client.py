"""Anthropic-backed LLM client: the determinism layer (cache + record/replay).

The ONLY module that imports `anthropic`, and it does so lazily in record mode only. Replay makes
zero model calls: a cache hit returns the recorded output byte-for-byte, a miss is a hard
`CacheMiss` (never a silent live call). Record mode (opt-in, key present) calls the API and appends.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .cache import append_cassette, cache_key, read_cassette
from .protocols import CacheMiss

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CASSETTE = _ROOT / "tests" / "cassettes" / "default.jsonl"


def _cassette_path(path: str | Path | None) -> Path:
    """Default cassette: env override, else the committed replay cassette."""
    if path is not None:
        return Path(path)
    return Path(os.environ.get("SAASWORLD_CASSETTE", _DEFAULT_CASSETTE))


class LLMClient:
    """Injected behind `LLMClientProto`. `mode` defaults to offline replay."""

    def __init__(self, *, mode: str | None = None, cassette: str | Path | None = None) -> None:
        # Default offline replay; `SAASWORLD_LLM_MODE=record` opts a live run into calling the API
        # (needed when a real agent sends novel NPC messages the cassette can't classify).
        self.mode = mode or os.environ.get("SAASWORLD_LLM_MODE", "replay")
        self.cassette = _cassette_path(cassette)
        self._recorded = read_cassette(self.cassette)

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
        key = cache_key(
            model=model, kind=kind, system=system, schema=schema,
            messages=messages, params=params, persona=persona,
        )
        hit = self._recorded.get(key)
        if hit is not None:
            output: dict[str, Any] = hit["output"]
            return output
        if self.mode != "record":
            raise CacheMiss(f"no cassette entry for {kind} key={key[:12]}… (replay makes no calls)")
        return self._record(key, kind, model, request or {})

    def _record(
        self, key: str, kind: str, model: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Record mode only: call the live API, extract the schema-shaped output, append it."""
        import anthropic  # lazy: imported only when actually recording

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("record mode needs ANTHROPIC_API_KEY")
        client = anthropic.Anthropic()
        resp = client.messages.create(**request)
        output = _extract_output(kind, resp)
        record = {"key": key, "kind": kind, "model": model, "output": output}
        append_cassette(self.cassette, record)
        self._recorded[key] = record
        return output


def _extract_output(kind: str, resp: Any) -> dict[str, Any]:
    """Pull the schema-forced payload out of an API response (record mode)."""
    if kind == "parse_intent":
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return {"intent": block.input["intent"]}
        raise RuntimeError("no tool_use block in classify_intent response")
    if kind == "render_reply":
        text = "".join(getattr(b, "text", "") for b in resp.content)
        return {"text": text}
    # extract: json_schema output arrives as a single text block of JSON
    import json

    text = "".join(getattr(b, "text", "") for b in resp.content)
    parsed: dict[str, Any] = json.loads(text)
    return parsed
