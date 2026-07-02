"""Minimal world seed for local runs and tests.

Provides just enough world (org/company plus a few projects, tasks and channels) to exercise the
action loop. The full frozen-instance scenario loader lives separately.
"""

from __future__ import annotations

from typing import Any


def load_bootstrap(name: str = "minimal") -> dict[str, Any]:
    """Return an initial world-state dict."""
    raise NotImplementedError
