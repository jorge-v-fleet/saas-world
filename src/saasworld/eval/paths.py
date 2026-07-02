"""Deterministic path reader: dotted read + ['index'] + minimal [?a==X && b==Y] filter.

A closed subset of JMESPath (no new dep). Scalar dotted paths return the value or MISSING; a
`[?...]` filter returns the list of matching dicts, and a trailing field projects it. Never raises
on a missing path — a missing scalar reads MISSING, a missing collection reads an empty list.
"""

from __future__ import annotations

from typing import Any


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<missing>"


MISSING: Any = _Missing()

# Interchangeable match keys: a single `references` matches membership in a `refs` list, and back.
_ALIASES = {"references": "refs", "refs": "references"}


def _tokens(path: str) -> list[tuple[str, str]]:
    """Split a path into ('name'|'index'|'filter', text) tokens."""
    toks: list[tuple[str, str]] = []
    i, n = 0, len(path)
    while i < n:
        c = path[i]
        if c == ".":
            i += 1
        elif c == "[":
            j = path.index("]", i)
            inner = path[i + 1 : j]
            if inner.startswith("?"):
                toks.append(("filter", inner[1:]))
            else:
                toks.append(("index", inner.strip().strip("'\"")))
            i = j + 1
        else:
            j = i
            while j < n and path[j] not in ".[":
                j += 1
            toks.append(("name", path[i:j]))
            i = j
    return toks


def _literal(tok: str) -> Any:
    """Parse a filter right-hand side: quoted string, bool, int, else bare string."""
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] in "'\"" and tok[-1] == tok[0]:
        return tok[1:-1]
    if tok == "true":
        return True
    if tok == "false":
        return False
    try:
        return int(tok)
    except ValueError:
        return tok


def _conds(expr: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for part in expr.split("&&"):
        key, _, rhs = part.partition("==")
        out.append((key.strip(), _literal(rhs)))
    return out


def _field(item: Any, key: str) -> Any:
    """Read a field from a dict, following the refs/references alias when the key is absent."""
    if not isinstance(item, dict):
        return None
    if key in item:
        return item[key]
    alias = _ALIASES.get(key)
    return item.get(alias) if alias else None


def _matches(item: Any, conds: list[tuple[str, Any]]) -> bool:
    for key, want in conds:
        got = _field(item, key)
        if got == want or (isinstance(got, list) and want in got):
            continue
        return False
    return True


def read(state: Any, path: str) -> Any:
    """Read `path` from a WorldState. Scalar -> value/MISSING; filter -> list (projected if a field
    trails). Missing paths never raise."""
    toks = _tokens(path)
    if not toks or toks[0][0] != "name":
        return MISSING
    node: Any = state.read(toks[0][1])
    for kind, arg in toks[1:]:
        if kind == "name":
            if isinstance(node, list):
                node = [_field(it, arg) for it in node]
            elif isinstance(node, dict):
                node = node.get(arg, MISSING)
            else:
                node = MISSING
        elif kind == "index":
            if isinstance(node, dict):
                node = node.get(arg, MISSING)
            elif isinstance(node, list):
                node = next(
                    (it for it in node if _field(it, "id") == arg or _field(it, "about") == arg),
                    MISSING,
                )
            else:
                node = MISSING
        else:  # filter
            conds = _conds(arg)
            node = [it for it in node if _matches(it, conds)] if isinstance(node, list) else []
    return node
