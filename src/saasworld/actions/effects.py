"""Bind an action's effect template + args -> concrete deltas (+ follow-up events)."""

from __future__ import annotations

from typing import Any


def _sub(node: Any, args: dict[str, Any]) -> Any:
    """Substitute `$argname` tokens; a whole-value `$arg` becomes args[arg] (missing -> None)."""
    if isinstance(node, str):
        return args.get(node[1:]) if node.startswith("$") else node
    if isinstance(node, dict):
        return {k: _sub(v, args) for k, v in node.items()}
    if isinstance(node, list):
        return [_sub(v, args) for v in node]
    return node


def _sub_path(path: str, args: dict[str, Any]) -> str:
    """Substitute `$seg` tokens per dotted segment (a value may itself be a dotted id)."""
    out: list[str] = []
    for seg in path.split("."):
        out.append(str(args.get(seg[1:])) if seg.startswith("$") else seg)
    return ".".join(out)


def bind_effect(
    entry: dict[str, Any], args: dict[str, Any], now: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (deltas, follow_ups) for a catalog entry bound with args. Fully deterministic.

    `set_each` expands into one `set` delta per key of its `$dict` value (per-field writes so the
    constrained-write guard is exercised leaf-by-leaf). follow_ups is [] in Wave 1.
    """
    effect = entry.get("effect")
    if not effect:
        return [], []
    deltas: list[dict[str, Any]] = []
    for op in effect:
        path = _sub_path(op["path"], args)
        if op["op"] == "set_each":
            fields = _sub(op.get("value"), args) or {}
            for key, val in fields.items():
                deltas.append({"op": "set", "path": f"{path}.{key}", "value": val})
        else:
            delta = {k: _sub(v, args) for k, v in op.items()}
            delta["path"] = path
            deltas.append(delta)
    return deltas, []
