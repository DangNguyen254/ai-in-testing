"""Pydantic model -> provider-safe JSON schema.

Providers support only a subset of JSON Schema for constrained output. This produces the
common subset: refs inlined, every object closed (``additionalProperties: false``) with all
properties required, and value constraints removed. Those constraints (ranges, lengths, item
counts) are still enforced locally by Pydantic when the response is validated.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_DROP_KEYS = {
    "title",
    "default",
    "examples",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "format",
}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    defs: dict[str, Any] = schema.pop("$defs", {})
    result = _convert(schema, defs, depth=0)
    assert isinstance(result, dict)
    return result


def _convert(node: Any, defs: dict[str, Any], depth: int) -> Any:
    if depth > 32:
        raise ValueError("Schema too deep (recursive models are not supported)")
    if isinstance(node, list):
        return [_convert(item, defs, depth + 1) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str):
        target = defs[ref.rsplit("/", 1)[-1]]
        merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return _convert(merged, defs, depth + 1)

    out = {k: _convert(v, defs, depth + 1) for k, v in node.items() if k not in _DROP_KEYS}
    if isinstance(node.get("properties"), dict):  # field names, not keywords: keep them all
        out["properties"] = {
            name: _convert(value, defs, depth + 1) for name, value in node["properties"].items()
        }
    if out.get("type") == "object" or "properties" in out:
        props = out.get("properties", {})
        out["properties"] = props
        out["required"] = list(props)
        out["additionalProperties"] = False
    return out
