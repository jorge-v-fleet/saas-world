"""Cassette cache: canonical cache key + JSONL read/write for record/replay.

Key = sha256 over a canonicalized request: sorted keys, no timestamps/uuids; persona referenced by
{id, version} (never inlined prose); body/artifact text verbatim. A param/schema/version change
invalidates the key. The cassette maps key -> recorded output; replay reads it, record appends.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..content_hash import canonicalize, sha256_hex


def cache_key(
    *,
    model: str,
    kind: str,
    system: str,
    schema: Any,
    messages: list[dict[str, Any]],
    params: dict[str, Any],
    persona: dict[str, str] | None,
) -> str:
    """Deterministic key over the canonical request (persona by id+version only)."""
    canonical = {
        "model": model,
        "kind": kind,
        "system": system,
        "schema": schema,
        "messages": messages,
        "params": params,
        "persona": persona,
    }
    return sha256_hex(canonicalize(canonical))


def read_cassette(path: Path) -> dict[str, dict[str, Any]]:
    """Load a JSONL cassette into {key: record}. Missing file -> empty (nothing recorded yet)."""
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rec = json.loads(line)
            out[rec["key"]] = rec
    return out


def append_cassette(path: Path, record: dict[str, Any]) -> None:
    """Append one record as a JSON line (record mode only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")
