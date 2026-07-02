"""Minimal world seed for local runs and tests.

Provides just enough world (org plus a few projects, tasks and channels) to exercise the action
loop. The full frozen-instance scenario loader lives separately.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_WORLD = Path(__file__).parents[2] / "data" / "world"


def _org_people() -> dict[str, Any]:
    """Load org nodes from data/world/org.json, keyed by id (fall back to a minimal set)."""
    try:
        nodes = json.loads((_WORLD / "org.json").read_text())["nodes"]
        return {n["id"]: {"title": n["title"], "name": n["name"]} for n in nodes}
    except (OSError, KeyError, ValueError):
        return {
            "org.pm_a": {"title": "Product Manager", "name": "Alex Rivera"},
            "org.fe_a1": {"title": "Frontend Engineer", "name": "Sam Torres"},
            "org.cto": {"title": "CTO", "name": "Rohit Malhotra"},
        }


def load_bootstrap(name: str = "minimal") -> dict[str, Any]:
    """Return an initial world-state dict (single seed 'minimal')."""
    return {
        "org": _org_people(),
        "projects": {
            "proj.checkout": {"name": "Checkout revamp", "owner": "org.pm_a"},
        },
        # Dot-free keys: tasks/blockers are dot-path-addressed to subfields, so their ids must
        # be single segments (a dotted id would dot-walk into a phantom nested node).
        "tasks": {
            "t1": {
                "project": "proj.checkout",
                "title": "Checkout UI",
                "owner": "org.fe_a1",
                "status": "todo",
            },
        },
        "blockers": {
            "b1": {"surfaced": False},
        },
        "chat": {
            "chan.checkout": {"members": ["org.pm_a", "org.fe_a1"], "log": []},
        },
        "messages": [],
        "email": [],
        "docs": [],
        "decisions": [],
        "calendar": [],
    }
