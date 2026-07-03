"""Co-generate `eval.json` from the same FactMap the world was assembled from.

Every predicate is bound to concrete IDs pulled from the FactMap — never a second source — so the
grader cannot reference an entity the world lacks. Weights are copied from the template shapes and
validated to sum to exactly 1.0; the `correct_action` set is derived from the deadline's movability.
"""

from __future__ import annotations

import json
from typing import Any

from .assemble import FactMap
from .render import substitute

_WEIGHT_EPS = 1e-9


class WeightsError(ValueError):
    """Emitted eval weights do not sum to 1.0."""


def _referenced_ids(factmap: FactMap, projected: Any) -> set[str]:
    """Entity ids the projected eval actually mentions.

    Scans the bound predicates for any dotted id-value drawn from the factmap, so an archetype
    whose eval references different ids still has each one existence-checked against the world.
    """
    text = json.dumps(projected)
    pool = set(factmap.ids.values())
    pool |= {v for v in factmap.bindings.values() if isinstance(v, str) and "." in v}
    return {i for i in pool if i in text}


def project_eval(factmap: FactMap, template: dict[str, Any]) -> dict[str, Any]:
    """Project the templated predicate shapes onto the resolved facts -> eval.json dict."""
    shapes = [substitute(s, factmap.bindings) for s in template["eval_shapes"]]
    checkpoint = [s for s in shapes if "source" not in s]
    artifacts = [s for s in shapes if "source" in s]

    total = sum(float(s["w"]) for s in shapes)
    if abs(total - 1.0) > _WEIGHT_EPS:
        raise WeightsError(f"eval weights sum to {total}, expected 1.0")

    meta = substitute(template["eval_checkpoint"], factmap.bindings)
    result = {
        "checkpoints": [{"id": meta["id"], "at": meta["at"], "predicates": checkpoint}],
        "artifact_predicates": artifacts,
        "guards": substitute(template.get("eval_guards", []), factmap.bindings),
    }

    missing = _referenced_ids(factmap, result) - factmap.world_ids()
    if missing:
        raise ValueError(f"eval references absent IDs {sorted(missing)}")
    return result
