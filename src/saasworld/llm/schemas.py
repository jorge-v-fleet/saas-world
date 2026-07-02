"""Build the schema-forced output shapes: classify_intent tool + extract json_schema.

Schema-forcing is the injection defence: the enum is the entire output space of `parse_intent`, and
the json_schema is the entire output space of `extract`. There is no free-text channel to hijack.
"""

from __future__ import annotations

from typing import Any

# Map an ExtractSchema field type to a JSON-schema type list (`|null` -> nullable).
_BASE = {"bool": "boolean", "date": "string", "string": "string", "null": "null"}


def classify_intent_tool(allowed_intents: list[str]) -> dict[str, Any]:
    """Strict tool: the only output is one enum member of `allowed_intents`."""
    return {
        "name": "classify_intent",
        "description": "Classify the message into exactly one intent.",
        "input_schema": {
            "type": "object",
            "properties": {"intent": {"type": "string", "enum": list(allowed_intents)}},
            "required": ["intent"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def _field_schema(type_str: str) -> dict[str, Any]:
    """`bool` -> boolean; `date|null` / `string|null` -> nullable string, etc."""
    types = [_BASE[t.strip()] for t in type_str.split("|")]
    return {"type": types[0] if len(types) == 1 else types}


def extract_json_schema(extract_schema: list[dict[str, Any]]) -> dict[str, Any]:
    """Closed object of exactly the schema's fields — no additional properties."""
    props = {f["field"]: _field_schema(f["type"]) for f in extract_schema}
    return {
        "type": "object",
        "properties": props,
        "required": [f["field"] for f in extract_schema],
        "additionalProperties": False,
    }
