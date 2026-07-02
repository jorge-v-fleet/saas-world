"""Structural interfaces that decouple the systems from each other."""

from __future__ import annotations

from typing import Any, Protocol

from .events import Event

Delta = dict[str, Any]  # {op, path, value?}


class StateWriter(Protocol):
    """The subset of the world state the Kernel depends on."""

    def apply(self, deltas: list[Delta], source: str) -> None: ...
    def read(self, path: str) -> Any: ...
    def snapshot(self) -> dict[str, Any]: ...
    def restore(self, snap: dict[str, Any]) -> None: ...


class KernelProto(Protocol):
    """The subset of the Kernel the Tool API depends on."""

    def now(self) -> int: ...
    def schedule(
        self,
        sim_time: int,
        actor: str,
        kind: str,
        payload: dict[str, Any],
        caused_by: int | None = None,
    ) -> int: ...
    def advance_until(self, t: int) -> list[Event]: ...
