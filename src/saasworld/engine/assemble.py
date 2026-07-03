"""Materialize the concrete world (seed / overlay / timeline) from the draw + bound IDs.

A thin, archetype-agnostic interpreter: it builds a binding env (bound ids, per-entity derivations,
template-declared `derive` values) then substitutes the template's `world` / overlay / `timeline`
blueprints through a small closed vocabulary (`repeat`, `_when`). The single resolved FactMap it
returns is the same read the eval projector uses, so world and grader can't drift. No randomness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .bind import Binding
from .render import cond, substitute
from .sample import Draw
from .substrate import Substrate, first_name, persona_id


@dataclass
class FactMap:
    draw: Draw
    ids: dict[str, str]
    bindings: dict[str, Any]
    agent: str
    activate: list[str]
    seed: dict[str, Any]
    overlay: dict[str, Any]
    timeline: dict[str, Any]
    # Archetype rules carried in-memory only (never serialized into the frozen instance).
    coherence: list[Any] = field(default_factory=list)
    solvers: dict[str, Any] = field(default_factory=dict)
    autonomous_npcs: bool = False  # template-declared; propagates into the frozen manifest

    def world_ids(self) -> set[str]:
        ids = {self.agent, *self.activate}
        for part in ("projects", "tasks", "blockers"):
            ids.update(e["id"] for e in self.seed.get(part, []))
        return ids


def _day(offset: str) -> int:
    return int(offset[1 : offset.index("T")])


def _content(template: dict[str, Any], btype: str) -> dict[str, Any]:
    """Type-specific blocker content, falling back to the generic `_default` block."""
    blocks = template["blockers"]
    block: dict[str, Any] = blocks.get(btype) or blocks["_default"]
    return block


def _derive(spec: dict[str, Any], env: dict[str, Any], substrate: Substrate) -> Any:
    """One template-declared derived value from the closed derive vocabulary."""
    if "draw" in spec:  # copy a draw slot (dotted name -> its env alias)
        return env[spec["draw"].replace(".", "_")]
    if "day_of" in spec:
        return _day(substitute(spec["day_of"], env))
    if "day_offset" in spec:
        o = spec["day_offset"]
        return f"D{int(substitute(o['base'], env)) + int(o['delta'])}T{o['time']}"
    if "select" in spec:
        s = spec["select"]
        return s["if_true"] if substitute(s["cond"], env) else s["if_false"]
    if "role_label" in spec:
        role = substrate.people[substitute(spec["role_label"], env)].role
        return spec["map"].get(role, spec["default"])
    if "interp" in spec:
        return substitute(spec["interp"], env)
    raise ValueError(f"unrecognized derive {spec!r}")


def _env(
    template: dict[str, Any], draw: Draw, binding: Binding, substrate: Substrate
) -> dict[str, Any]:
    """Substitution env: bound ids, per-entity derivations, draw slots, template derives."""
    slots = template["slots"]
    env: dict[str, Any] = {"agent": binding.agent}
    bound = {slots[name].get("as", name): cid for name, cid in binding.ids.items()}
    bound["pointer"] = binding.pointer or binding.agent  # 1-hop: agent owns the dependent task
    env.update(bound)
    env["has_pointer"] = binding.pointer is not None
    for alias, cid in bound.items():
        env[f"{alias}_persona"] = persona_id(cid)
        person = substrate.people.get(cid)
        if person is not None:
            env[f"{alias}_first"] = first_name(person)
            env[f"{alias}_mgr"] = person.reports_to
    for slot, value in draw.items():  # every draw slot, keyed dot -> underscore
        env[slot.replace(".", "_")] = value
    content = _content(template, draw["blocker.type"])
    env["blocker"] = substitute(content["blocker"]["id"], env)
    env["label_template"] = content["label"]
    for d in template["derive"]:
        env[d["name"]] = _derive(d, env, substrate)
    return env


def _expand(node: Any, env: dict[str, Any]) -> Any:
    """Substitute a blueprint, expanding `repeat` nodes and dropping falsy `_when` list items."""
    if isinstance(node, list):
        out: list[Any] = []
        for item in node:
            if isinstance(item, dict) and "repeat" in item:
                out.extend(_repeat(item["repeat"], env))
            elif isinstance(item, dict) and "_when" in item:
                if cond(item["_when"], env):
                    out.append(_expand({k: v for k, v in item.items() if k != "_when"}, env))
            else:
                out.append(_expand(item, env))
        return out
    if isinstance(node, dict):
        return {k: _expand(v, env) for k, v in node.items()}
    return substitute(node, env)


def _repeat(spec: dict[str, Any], env: dict[str, Any]) -> list[Any]:
    """`{count, as, node}` -> N substituted copies with the 1-based index bound to `as`."""
    n = int(substitute(spec["count"], env))
    return [_expand(spec["node"], {**env, spec["as"]: i + 1}) for i in range(n)]


def _overlays(content: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """Persona-token -> overlay blueprint; a falsy `_when` (e.g. no pointer) drops the entry."""
    out: dict[str, Any] = {}
    for key_tok, bp in content["overlays"].items():
        if "_when" in bp and not cond(bp["_when"], env):
            continue
        body = {k: v for k, v in bp.items() if k != "_when"}
        out[substitute(key_tok, env)] = substitute(body, env)
    return out


def assemble(
    template: dict[str, Any], draw: Draw, binding: Binding, substrate: Substrate
) -> FactMap:
    env = _env(template, draw, binding, substrate)
    content = _content(template, draw["blocker.type"])
    world = template["world"]

    seed = {
        "projects": [substitute(bp, env) for bp in world["projects"].values()],
        "tasks": _expand(world["tasks"], env),
        "blockers": [substitute(content["blocker"], env), *_expand(world["blockers"], env)],
        "surfaces": _expand(world["surfaces"], env),
    }

    return FactMap(
        draw=draw, ids=binding.ids, bindings=env, agent=binding.agent,
        activate=binding.activate, seed=seed, overlay=_overlays(content, env),
        timeline={"scripted": _expand(template["timeline"]["scripted"], env)},
        coherence=template.get("coherence", []), solvers=template.get("solvers", {}),
        autonomous_npcs=bool(template.get("autonomous_npcs", False)),
    )
