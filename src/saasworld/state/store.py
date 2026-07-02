"""WorldState — namespaced world model. Mutated only via apply(); reads are stable between events."""

from __future__ import annotations

from typing import Any


class WorldState:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = initial if initial is not None else {}

    def read(self, path: str) -> Any:
        """Dotted-path read (e.g. 'tasks.T1.status'); return None if absent."""
        raise NotImplementedError

    def view(self, scope: dict[str, Any]) -> dict[str, Any]:
        """Projection filtered by a view_scope (people/projects/channels)."""
        raise NotImplementedError

    def apply(self, deltas: list[dict[str, Any]], source: str) -> None:
        """Apply delta-DSL ops in order. Enforce the constrained-write guard per op."""
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:
        """Order-stable deep copy; restore(snapshot()) is identity."""
        raise NotImplementedError

    def restore(self, snap: dict[str, Any]) -> None:
        raise NotImplementedError
