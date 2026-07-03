"""Constrained-write guard — agent-sourced deltas may never touch derived/graded paths."""

from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatchcase

# Base glob-style denied paths (the floor); only source == "system" may write these.
# Ids are dot-free, so `*` covers exactly one dotted segment (root.<id>.leaf).
DENIED_PATHS = (
    "blockers.*.surfaced",
    "tasks.*.blocked_by",
    "decisions.*.correct",
)


def _matches(pattern: str, path: str) -> bool:
    """Glob match where each `*` covers exactly one dotted segment."""
    pat_segs, path_segs = pattern.split("."), path.split(".")
    if len(pat_segs) != len(path_segs):
        return False
    return all(fnmatchcase(seg, pat) for pat, seg in zip(pat_segs, path_segs, strict=True))


def check_write_allowed(path: str, source: str, extra: Iterable[str] = ()) -> None:
    """Raise PermissionError if a non-system `source` writes a denied path.

    Enforces the base floor UNION any per-instance `extra` denied globs.
    """
    if source == "system":
        return
    for pattern in (*DENIED_PATHS, *extra):
        if _matches(pattern, path):
            raise PermissionError(f"source {source!r} may not write denied path {path!r}")
