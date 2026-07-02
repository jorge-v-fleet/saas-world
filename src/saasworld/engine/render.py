"""Tiny deterministic substitution over authored blueprints.

`$name` as a whole value is replaced by the binding (any type); `${name}` inside a string
interpolates its stringified value. Missing bindings raise — a blueprint may only reference bound
slots, so a typo can never silently emit a dangling token.
"""

from __future__ import annotations

import re
from typing import Any

_WHOLE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")
_INTERP = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def substitute(node: Any, bindings: dict[str, Any]) -> Any:
    """Recursively resolve `$name` / `${name}` against `bindings`."""
    if isinstance(node, str):
        whole = _WHOLE.match(node)
        if whole:
            return bindings[whole.group(1)]
        return _INTERP.sub(lambda m: str(bindings[m.group(1)]), node)
    if isinstance(node, dict):
        return {k: substitute(v, bindings) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute(v, bindings) for v in node]
    return node
