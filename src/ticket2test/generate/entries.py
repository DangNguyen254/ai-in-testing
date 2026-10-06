"""Build new data entries from the nearest existing entry (deterministic).

For each new entry the LLM chooses which base sections to keep and which values to change;
this module does the copying:

1. start from the base (the nearest existing entry), never inheriting its id or per-entry
   overrides (priority, skip);
2. keep only the chosen sections, deep-copied unchanged;
3. re-label strings that embed the base test's name (``policy-orders-detail-cancel``) with
   the new test's name;
4. apply the changes (dotted paths; list items by index), then set the id.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

PathPart = str | int


class EntryError(ValueError):
    """A plan can't be applied to the base entry (unknown section, bad path or value)."""


def parse_path(path: str) -> list[PathPart]:
    """``interactions.0.response.body.quantity`` -> ["interactions", 0, "response", ...]."""
    if not path or path.startswith(".") or path.endswith(".") or ".." in path:
        raise EntryError(f"invalid path {path!r}")
    return [int(part) if part.isdigit() else part for part in path.split(".")]


def set_path(target: dict[str, Any], path: str, value: Any) -> None:
    """Set a value, creating missing object keys. A list index may equal the length (append)."""
    parts = parse_path(path)
    node: Any = target
    for depth, part in enumerate(parts):
        last = depth == len(parts) - 1
        where = ".".join(str(p) for p in parts[: depth + 1])
        if isinstance(part, int):
            if not isinstance(node, list):
                raise EntryError(f"{where}: not a list")
            if part > len(node):
                raise EntryError(f"{where}: index {part} is past the end ({len(node)} items)")
            if part == len(node):
                node.append(copy.deepcopy(value) if last else {})
                node = node[part]
                continue
            if last:
                node[part] = copy.deepcopy(value)
                return
            node = node[part]
        else:
            if not isinstance(node, dict):
                raise EntryError(f"{where}: not an object")
            if last:
                node[part] = copy.deepcopy(value)
                return
            node = node.setdefault(part, {})


def delete_path(target: dict[str, Any], path: str) -> None:
    parts = parse_path(path)
    node: Any = target
    for part in parts[:-1]:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise EntryError(f"{path}: not found") from exc
    try:
        del node[parts[-1]]
    except (KeyError, IndexError, TypeError) as exc:
        raise EntryError(f"{path}: not found") from exc


def name_forms(function_name: str, test_prefix: str = "test") -> list[str]:
    """Spellings of a test name that seed values embed, longest first.

    ``test_orders_detail_cancel`` -> the name itself, ``orders_detail_cancel``,
    ``orders-detail-cancel``.
    """
    stem = function_name.removeprefix(f"{test_prefix}_")
    forms = {function_name, stem, stem.replace("_", "-")}
    return sorted((f for f in forms if f), key=len, reverse=True)


def relabel(value: Any, old_name: str, new_name: str, test_prefix: str = "test") -> Any:
    """Replace the base test's name (in its spellings) with the new test's, in string values."""
    if old_name == new_name:
        return copy.deepcopy(value)
    old_forms = name_forms(old_name, test_prefix)
    new_forms = dict(zip(old_forms, _matching_forms(old_forms, new_name, test_prefix), strict=True))
    pattern = re.compile("|".join(re.escape(f) for f in old_forms))

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return pattern.sub(lambda m: new_forms[m.group(0)], node)
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        return node

    return walk(value)


def _matching_forms(old_forms: list[str], new_name: str, test_prefix: str) -> list[str]:
    stem = new_name.removeprefix(f"{test_prefix}_")
    out = []
    for form in old_forms:
        if form.startswith(f"{test_prefix}_"):
            out.append(new_name)
        elif "-" in form:
            out.append(stem.replace("_", "-"))
        else:
            out.append(stem)
    return out


def function_of(test_id: str) -> str:
    return test_id.split("[", 1)[0]


def build_entry(
    base: dict[str, Any],
    base_id: str,
    test_id: str,
    copy_sections: list[str],
    changes: list[tuple[str, str, str]],
    id_field: str = "id",
    per_entry_keys: list[str] | None = None,
    test_prefix: str = "test",
) -> dict[str, Any]:
    """One new entry. ``changes`` are (op, path, value_json) with op "set" or "delete"."""
    never = {id_field, *(per_entry_keys or [])}
    unknown = [s for s in copy_sections if s not in base or s in never]
    if unknown:
        available = [k for k in base if k not in never]
        raise EntryError(
            f"{test_id}: copy_sections {unknown} are not sections of the base entry "
            f"{base_id!r} (available: {available})"
        )
    entry: dict[str, Any] = {id_field: test_id}
    for section in copy_sections:
        entry[section] = relabel(
            base[section], function_of(base_id), function_of(test_id), test_prefix
        )
    for op, path, value_json in changes:
        if parse_path(path)[0] == id_field:
            raise EntryError(f"{test_id}: {path!r}: the id is set automatically")
        if op == "delete":
            delete_path(entry, path)
            continue
        try:
            value = json.loads(value_json)
        except json.JSONDecodeError as exc:
            raise EntryError(f"{test_id}: {path!r}: value_json is not valid JSON: {exc}") from exc
        set_path(entry, path, value)
    return entry


__all__ = [
    "EntryError",
    "build_entry",
    "delete_path",
    "function_of",
    "name_forms",
    "parse_path",
    "relabel",
    "set_path",
]
