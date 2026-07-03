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


def _literal(token: str) -> Any:
    if token.lstrip("-").isdigit():
        return int(token)
    if token in ("true", "false"):
        return token == "true"
    return token.strip("'\"")


def cond(expr: str, scope: dict[str, Any]) -> bool:
    """Evaluate a tiny `<ref> (==|!=) <literal>` / bare-truthy condition against `scope`.

    A `$name` or bare `name` ref reads `scope`; the RHS is an int/bool/string literal. No operator
    means: is the referenced value truthy.
    """
    for op in ("==", "!="):
        if op in expr:
            lhs, rhs = (s.strip() for s in expr.split(op, 1))
            equal = scope.get(lhs.lstrip("$")) == _literal(rhs)
            return equal if op == "==" else not equal
    return bool(scope.get(expr.lstrip("$")))
