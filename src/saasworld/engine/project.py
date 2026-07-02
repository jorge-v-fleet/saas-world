"""Co-generate `eval.json` from the same FactMap the world was assembled from.

Every predicate is bound to concrete IDs pulled from the FactMap — never a second source — so the
grader cannot reference an entity the world lacks. Weights are copied from the template shapes and
validated to sum to exactly 1.0; the `correct_action` set is derived from the deadline's movability.
"""

from __future__ import annotations

from typing import Any

from .assemble import FactMap
from .render import substitute

_WEIGHT_EPS = 1e-9


class WeightsError(ValueError):
    """Emitted eval weights do not sum to 1.0."""


def _referenced_ids(factmap: FactMap) -> set[str]:
    ids = factmap.ids
    return {ids["blocker.holder"], ids["critical_project"], ids["stakeholder"],
            factmap.bindings["blocker"]}


def project_eval(factmap: FactMap, template: dict[str, Any]) -> dict[str, Any]:
    """Project the templated predicate shapes onto the resolved facts -> eval.json dict."""
    shapes = [substitute(s, factmap.bindings) for s in template["eval_shapes"]]
    checkpoint = [s for s in shapes if "source" not in s]
    artifacts = [s for s in shapes if "source" in s]

    total = sum(float(s["w"]) for s in shapes)
    if abs(total - 1.0) > _WEIGHT_EPS:
        raise WeightsError(f"eval weights sum to {total}, expected 1.0")

    meta = substitute(template["eval_checkpoint"], factmap.bindings)
    world_ids = factmap.world_ids()
    missing = _referenced_ids(factmap) - world_ids
    if missing:
        raise ValueError(f"eval references absent IDs {sorted(missing)}")

    return {
        "checkpoints": [{"id": meta["id"], "at": meta["at"], "predicates": checkpoint}],
        "artifact_predicates": artifacts,
        "guards": substitute(template.get("eval_guards", []), factmap.bindings),
    }
