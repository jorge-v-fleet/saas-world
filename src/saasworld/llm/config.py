"""Resolve the two decoupled LLM roles from config/settings.toml + env overrides.

Each role (`npc_parser`, `evaluator`) overrides `model` independently and falls back to the shared
`[llm].model`. Env wins over file. The toml is read-only operational config, never edited here.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_SETTINGS = _ROOT / "config" / "settings.toml"

_ROLE_ENV = {"npc_parser": "SAASWORLD_NPC_PARSER_MODEL", "evaluator": "SAASWORLD_EVALUATOR_MODEL"}


@lru_cache(maxsize=1)
def _file() -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads(_SETTINGS.read_text())
    llm: dict[str, Any] = data.get("llm", {})
    return llm


def model_for(role: str) -> str:
    """Resolve a role's model: role env > role file > shared env > shared file."""
    llm = _file()
    if env := os.environ.get(_ROLE_ENV[role]):
        return env
    if role_model := llm.get(role, {}).get("model"):
        return str(role_model)
    if env := os.environ.get("SAASWORLD_LLM_MODEL"):
        return env
    return str(llm["model"])


def request_params() -> dict[str, Any]:
    """Fixed record-time request shape (part of the cache key). No temperature/top_p/seed."""
    llm = _file()
    return {
        "thinking": {"type": llm.get("thinking", "disabled")},
        "output_config": {"effort": llm.get("effort", "low")},
        "max_tokens": 1024,
    }
