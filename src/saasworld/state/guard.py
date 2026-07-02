"""Constrained-write guard — agent-sourced deltas may never touch derived/graded paths."""

from __future__ import annotations

# Glob-style denied paths; only source == "system" may write these.
DENIED_PATHS = (
    "blockers.*.surfaced",
    "tasks.*.blocked_by",
    "decisions.*.correct",
)


def check_write_allowed(path: str, source: str) -> None:
    """Raise PermissionError if a non-system `source` writes a denied path."""
    raise NotImplementedError
