"""Fixtures for the seeding-engine suite: substrate, template, the pinned golden seed, pipeline."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from saasworld.engine.assemble import FactMap
from saasworld.engine.gate import clear_cache, run_pipeline
from saasworld.engine.substrate import Substrate, load_substrate, load_template

Pipeline = Callable[[int], tuple[FactMap, dict[str, Any]]]


@pytest.fixture
def substrate() -> Substrate:
    return load_substrate()


@pytest.fixture
def template() -> dict[str, Any]:
    return load_template("hidden-critical-blocker")


@pytest.fixture
def golden_seed(template: dict[str, Any]) -> int:
    return int(template["example_binding"]["_seed"])


@pytest.fixture
def pipeline(template: dict[str, Any], substrate: Substrate) -> Pipeline:
    def _run(seed: int) -> tuple[FactMap, dict[str, Any]]:
        return run_pipeline(template, seed, substrate)

    return _run


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    clear_cache()
    yield
    clear_cache()
