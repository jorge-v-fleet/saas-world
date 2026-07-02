"""Scenario Loader — validate a frozen instance, seed the world, register NPCs, schedule timeline.

Recomputes `dataset_version` over the instance content and refuses to load on a declared mismatch
(no silent drift). Seeds `WorldState` from `seed.json`, builds each active NPC's runtime config
(base persona ⊕ overlay), registers it with the NPC Engine, and schedules every timeline entry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..content_hash import dataset_version
from ..kernel import Kernel
from ..npc.engine import NPCEngine

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_SCENARIOS = _DATA / "scenarios"
_MINUTES_PER_DAY = 24 * 60


class ScenarioError(RuntimeError):
    """Raised when a frozen instance fails validation (e.g. dataset_version mismatch)."""


@dataclass
class LoadedScenario:
    scenario_id: str
    dataset_version: str
    engine: NPCEngine
    eval_ground_truth: dict[str, Any]
    t0: int = 0


def _read(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def _resolve(path: str | Path) -> Path:
    """Accept a directory path or a bare scenario name under data/scenarios/."""
    p = Path(path)
    return p if p.exists() else _SCENARIOS / str(path)


def offset_to_minutes(offset: str) -> int:
    """`D<day>T<HH:MM>` -> integer sim-minutes from t0 (D1T00:00). D1 is the first working day."""
    m = re.fullmatch(r"D(\d+)T(\d{2}):(\d{2})", offset)
    if m is None:
        raise ScenarioError(f"bad time offset {offset!r}")
    day, hh, mm = int(m[1]), int(m[2]), int(m[3])
    return (day - 1) * _MINUTES_PER_DAY + hh * 60 + mm


def _nest(partition: dict[str, Any], dotted_id: str, fields: dict[str, Any]) -> None:
    """Store `fields` at a dotted id, walking it into nested dicts (so reads dot-path in)."""
    node = partition
    segs = dotted_id.split(".")
    for seg in segs[:-1]:
        node = node.setdefault(seg, {})
    node[segs[-1]] = fields


def _fields(entity: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entity.items() if k != "id" and not k.startswith("_")}


def _org_people() -> dict[str, Any]:
    """Live cast (agent + active tiers) from the base org, keyed by structural id."""
    nodes = _read(_DATA / "world" / "org.json")["nodes"]
    return {
        n["id"]: {"title": n["title"], "name": n["name"], "reports_to": n["reports_to"]}
        for n in nodes
        if n["tier"] in ("agent", "active")
    }


def _seed_world(seed: dict[str, Any]) -> dict[str, Any]:
    """Build the initial world dict from seed.json layered on the base org."""
    world: dict[str, Any] = {
        "org": _org_people(),
        "projects": {},
        "tasks": {},
        "blockers": {},
        "chat": {},
        "email": [],
        "calendar": [],
        "docs": [],
        "surfaces": {},
        "messages": [],
        "decisions": [],
    }
    for proj in seed.get("projects", []):
        _nest(world["projects"], proj["id"], _fields(proj))
    for task in seed.get("tasks", []):
        _nest(world["tasks"], task["id"], _fields(task))
    for blocker in seed.get("blockers", []):
        _nest(world["blockers"], blocker["id"], _fields(blocker))
    surfaces = seed.get("surfaces", {})
    for chan in surfaces.get("chat", []):
        world["chat"][chan["id"]] = _fields(chan)
    world["email"] = [_fields(e) | {"id": e["id"]} for e in surfaces.get("email", [])]
    world["calendar"] = [_fields(c) | {"id": c["id"]} for c in surfaces.get("calendar", [])]
    world["docs"] = [_fields(d) | {"id": d["id"]} for d in surfaces.get("docs", [])]
    world["surfaces"] = {"transcripts": surfaces.get("transcripts", [])}
    return world


def _personas_by_org() -> dict[str, dict[str, Any]]:
    """Base persona packs indexed by their org_ref."""
    packs = (_read(p) for p in sorted((_DATA / "personas").glob("*.json")))
    return {p["org_ref"]: p for p in packs}


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Runtime config = base persona ⊕ scenario overlay (annotations dropped)."""
    cfg = {k: v for k, v in base.items() if not k.startswith("_")}
    cfg.update({k: v for k, v in overlay.items() if not k.startswith("_")})
    return cfg


def _timeline_payload(ev: dict[str, Any]) -> dict[str, Any]:
    """Turn a scripted entry into an event payload the default Kernel path can apply."""
    if ev["type"] == "npc_message":
        msg = {k: ev[k] for k in ("from", "to", "intent", "about", "note") if k in ev}
        return {"deltas": [{"op": "append", "path": "messages", "value": msg}], "follow_ups": []}
    return {"deltas": [], "follow_ups": [], "event_ref": ev.get("event_ref")}


def load(path: str | Path, kernel: Kernel) -> LoadedScenario:
    """Validate + seed + register NPCs + schedule timeline against `kernel`. Returns the handle."""
    root = _resolve(path)
    manifest = _read(root / "scenario.json")
    seed = _read(root / "seed.json")
    overlays = _read(root / "personas.overlay.json")
    timeline = _read(root / "timeline.json")
    eval_gt = _read(root / "eval.json")

    instance = {"seed": seed, "overlay": overlays, "timeline": timeline, "eval": eval_gt}
    version = dataset_version(instance)
    declared = manifest.get("dataset_version")
    if declared is not None and declared != version:
        raise ScenarioError(f"dataset_version mismatch: manifest {declared} != computed {version}")

    kernel.state.restore(_seed_world(seed))

    engine = NPCEngine()
    packs = _personas_by_org()
    for org_id in manifest.get("activate", []):
        base = packs.get(org_id)
        if base is None:
            continue
        engine.register_npc(_merge(base, overlays.get(base["id"], {})))
    engine.attach(kernel)

    for ev in timeline.get("scripted", []):
        kernel.schedule(offset_to_minutes(ev["at"]), ev.get("from", "system"),
                        ev["type"], _timeline_payload(ev))

    return LoadedScenario(manifest["id"], version, engine, eval_gt)
