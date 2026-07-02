"""Content-addressed hashing for scenario data.

Canonicalize (sort keys, compact whitespace, strip `_`-prefixed annotation fields) -> sha256.
Deterministic and machine-independent: reformatting or annotation edits never change a hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _strip(value: Any) -> Any:
    """Recursively drop `_`-prefixed dict keys (authoring annotations)."""
    if isinstance(value, dict):
        return {
            k: _strip(v)
            for k, v in value.items()
            if not (isinstance(k, str) and k.startswith("_"))
        }
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def canonicalize(value: Any) -> str:
    """Stable canonical JSON: annotations stripped, keys sorted, whitespace compacted."""
    return json.dumps(_strip(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_value(value: Any) -> str:
    """sha256 of a value's canonical form."""
    return sha256_hex(canonicalize(value))


def file_hash(path: Path) -> str:
    """Content hash of a JSON file (canonicalized, so formatting is irrelevant)."""
    return hash_value(json.loads(Path(path).read_text()))


def subtree_hash(directory: Path) -> str:
    """Order-stable hash over every `*.json` under `directory`, keyed by relative posix path."""
    root = Path(directory)
    files = sorted(root.rglob("*.json"))
    lines = [f"{p.relative_to(root).as_posix()}:{file_hash(p)}" for p in files]
    return sha256_hex("\n".join(lines))


def dataset_version(dataset: dict[str, Any] | Path | str) -> str:
    """Version tag for a dataset: a directory (subtree) or an in-memory instance dict."""
    if isinstance(dataset, (str, Path)) and Path(dataset).is_dir():
        return "sha256:" + subtree_hash(Path(dataset))
    return "sha256:" + hash_value(dataset)


def instance_hash(instance: dict[str, Any]) -> str:
    """Version tag for a frozen instance assembled in memory (seed/overlay/timeline/eval)."""
    return "sha256:" + hash_value(instance)
