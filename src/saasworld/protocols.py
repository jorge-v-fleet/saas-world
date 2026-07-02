"""Structural interfaces so each system can be tested in isolation with fakes."""

from __future__ import annotations

from typing import Any, Protocol

from .events import Event

Delta = dict[str, Any]  # {op, path, value?}


class StateWriter(Protocol):
    """What the Kernel needs from World State (inject a fake in kernel tests)."""

    def apply(self, deltas: list[Delta], source: str) -> None: ...
    def read(self, path: str) -> Any: ...
    def snapshot(self) -> dict[str, Any]: ...
    def restore(self, snap: dict[str, Any]) -> None: ...


class KernelProto(Protocol):
    """What the Tool API needs from the Kernel (inject a fake in toolapi tests)."""

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
