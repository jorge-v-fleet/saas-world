"""World partitions + path validation."""

from __future__ import annotations

# core partitions (enabled)
CORE_PARTITIONS = (
    "org",
    "projects",
    "tasks",
    "blockers",
    "surfaces",
    "chat",
    "email",
    "calendar",
    "docs",
    "decisions",
    "messages",
)
# reserved partitions (disabled)
RESERVED_PARTITIONS = ("cust", "fin", "seas")


def validate_path(path: str) -> None:
    """Raise ValueError if the path's root segment isn't an enabled partition."""
    raise NotImplementedError
