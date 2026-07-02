"""Delta-DSL — the only vocabulary for state mutation."""

from __future__ import annotations

from typing import Any

OPS = ("set", "append", "inc", "link", "unlink")


def _walk(data: dict[str, Any], path: str) -> tuple[dict[str, Any], str]:
    """Descend `path`, creating intermediate dicts; return (parent, leaf)."""
    segs = path.split(".")
    if not path or "" in segs:
        raise ValueError(f"malformed path {path!r}")
    node = data
    for seg in segs[:-1]:
        nxt = node.setdefault(seg, {})
        if not isinstance(nxt, dict):
            raise ValueError(f"path segment {seg!r} is not a dict in {path!r}")
        node = nxt
    return node, segs[-1]


def _as_list(parent: dict[str, Any], leaf: str) -> list[Any]:
    """Return the list at parent[leaf], auto-creating []; raise if a non-list exists."""
    if leaf not in parent:
        parent[leaf] = []
    target = parent[leaf]
    if not isinstance(target, list):
        raise ValueError(f"target {leaf!r} is not a list")
    return target


def apply_delta(data: dict[str, Any], delta: dict[str, Any]) -> None:
    """Apply one {op, path, value?} op to `data` in place. Raise on unknown op / bad path."""
    op = delta["op"]
    if op not in OPS:
        raise ValueError(f"unknown op {op!r}")
    parent, leaf = _walk(data, delta["path"])
    value = delta.get("value")
    if op == "set":
        parent[leaf] = value
    elif op == "append":
        _as_list(parent, leaf).append(value)
    elif op == "inc":
        parent[leaf] = parent.get(leaf, 0) + value
    elif op == "link":
        target = _as_list(parent, leaf)
        if value not in target:
            target.append(value)
    elif op == "unlink":
        target = _as_list(parent, leaf)
        if value in target:
            target.remove(value)
