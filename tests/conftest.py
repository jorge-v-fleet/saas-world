"""Shared fixtures and lightweight test doubles."""

from __future__ import annotations

from typing import Any

import pytest

from saasworld.events import Event


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Rewrite golden files instead of asserting against them.",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-golden"))


class FakeState:
    """In-memory world-state stand-in that records applied deltas."""

    def __init__(self) -> None:
        self.applied: list[tuple[list[dict[str, Any]], str]] = []
        self._data: dict[str, Any] = {}

    def apply(self, deltas: list[dict[str, Any]], source: str) -> None:
        self.applied.append((deltas, source))

    def read(self, path: str) -> Any:
        return self._data.get(path)

    def snapshot(self) -> dict[str, Any]:
        return {"data": dict(self._data), "applied": list(self.applied)}

    def restore(self, snap: dict[str, Any]) -> None:
        self._data = dict(snap["data"])
        self.applied = list(snap["applied"])


class FakeKernel:
    """In-memory Kernel stand-in that records scheduled events."""

    def __init__(self) -> None:
        self.t = 0
        self.scheduled: list[Event] = []
        self._seq = 0

    def now(self) -> int:
        return self.t

    def schedule(
        self,
        sim_time: int,
        actor: str,
        kind: str,
        payload: dict[str, Any],
        caused_by: int | None = None,
    ) -> int:
        self._seq += 1
        self.scheduled.append(Event(self._seq, sim_time, actor, kind, payload, caused_by))
        return self._seq

    def advance_until(self, t: int) -> list[Event]:
        self.t = t
        return []


@pytest.fixture
def fake_state() -> FakeState:
    return FakeState()


@pytest.fixture
def fake_kernel() -> FakeKernel:
    return FakeKernel()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from saasworld.api.app import create_app

    return TestClient(create_app())
