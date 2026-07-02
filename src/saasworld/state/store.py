"""WorldState — namespaced world model. Mutated only via apply(); reads stable between events."""

from __future__ import annotations

import copy
from typing import Any

from .deltas import apply_delta
from .guard import check_write_allowed
from .schema import validate_path

# view_scope key -> world partition it projects.
_SCOPE_PARTITIONS = {"people": "org", "projects": "projects", "channels": "chat"}


class WorldState:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = initial if initial is not None else {}

    def read(self, path: str) -> Any:
        """Dotted-path read (e.g. 'tasks.T1.status'); return None if absent."""
        node: Any = self._data
        for seg in path.split("."):
            if not isinstance(node, dict) or seg not in node:
                return None
            node = node[seg]
        return node

    def view(self, scope: dict[str, Any]) -> dict[str, Any]:
        """Projection filtered by a view_scope (people/projects/channels)."""
        out: dict[str, Any] = {}
        for key, partition in _SCOPE_PARTITIONS.items():
            ids = scope.get(key)
            if ids is None:
                continue
            source = self._data.get(partition, {})
            out[partition] = {i: source[i] for i in ids if i in source}
        return out

    def apply(self, deltas: list[dict[str, Any]], source: str) -> None:
        """Apply delta-DSL ops in order. Enforce the constrained-write guard per op."""
        for delta in deltas:
            validate_path(delta["path"])
            check_write_allowed(delta["path"], source)
            apply_delta(self._data, delta)

    def snapshot(self) -> dict[str, Any]:
        """Order-stable deep copy; restore(snapshot()) is identity."""
        return copy.deepcopy(self._data)

    def restore(self, snap: dict[str, Any]) -> None:
        self._data = copy.deepcopy(snap)
