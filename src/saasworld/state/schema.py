"""World partitions + path validation."""

from __future__ import annotations

# core partitions (on in Wave 1)
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
# reserved partitions (off in Wave 1)
RESERVED_PARTITIONS = ("cust", "fin", "seas")


def validate_path(path: str) -> None:
    """Raise ValueError if the path's root segment isn't an enabled partition."""
    raise NotImplementedError
