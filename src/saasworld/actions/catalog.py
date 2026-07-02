"""Load + validate the action catalog (data/actions.json)."""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from saasworld.state.guard import DENIED_PATHS
from saasworld.state.schema import CORE_PARTITIONS

CLOCK_CLASSES = ("observe", "mutate", "advance")


def _writes_denied(path: str) -> bool:
    """True if `path` matches any denied glob (each `*` = one dotted segment)."""
    segs = path.split(".")
    for pattern in DENIED_PATHS:
        pat = pattern.split(".")
        if len(pat) == len(segs) and all(
            fnmatchcase(s, p) for p, s in zip(pat, segs, strict=True)
        ):
            return True
    return False


def _validate_effect(effect: Any, verb: str) -> None:
    if not isinstance(effect, list):
        raise ValueError(f"{verb}: effect must be a list of delta ops")
    for delta in effect:
        path = delta.get("path") if isinstance(delta, dict) else None
        if not isinstance(path, str) or not path:
            raise ValueError(f"{verb}: effect delta missing a string 'path'")
        if path.split(".", 1)[0] not in CORE_PARTITIONS:
            raise ValueError(f"{verb}: effect path root of {path!r} is not a valid partition")
        if _writes_denied(path):
            raise ValueError(f"{verb}: effect writes denied path {path!r}")


def load_catalog(path: Path) -> dict[str, dict[str, Any]]:
    """Return {verb: entry}, validating every entry. `_`-prefixed keys are annotations."""
    data = json.loads(Path(path).read_text())
    catalog: dict[str, dict[str, Any]] = {}
    for entry in data.get("actions", []):
        verb = entry.get("id")
        if not verb:
            raise ValueError("catalog entry missing 'id'")
        cls = entry.get("class")
        if cls not in CLOCK_CLASSES:
            raise ValueError(f"{verb}: class {cls!r} not in {CLOCK_CLASSES}")
        if "args" not in entry:
            raise ValueError(f"{verb}: missing args schema")
        effect = entry.get("effect")
        if cls == "mutate" and not isinstance(effect, list):
            raise ValueError(f"{verb}: mutate entry needs a structured effect")
        if effect is not None:
            _validate_effect(effect, verb)
        catalog[verb] = entry
    return catalog
