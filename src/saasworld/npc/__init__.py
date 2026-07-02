"""Reactive rule-based NPC engine (decision core + reply renderer + Kernel handlers)."""

from __future__ import annotations

from .decision import Decision, decide
from .engine import NPCEngine
from .reply import render

__all__ = ["Decision", "NPCEngine", "decide", "render"]
