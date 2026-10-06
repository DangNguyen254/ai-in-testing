"""JSON data files in the suite's style (indent, key spacing, final newline, layout)."""

from __future__ import annotations

import json
from typing import Any

from ticket2test.config import DataSettings, JsonStyle
from ticket2test.models.chunk import DataFormat


def format_json(value: Any, style: JsonStyle) -> str:
    text = json.dumps(
        value,
        indent=style.indent,
        separators=(style.item_separator, style.key_separator),
        ensure_ascii=style.ensure_ascii,
    )
    return text + "\n" if style.final_newline else text


def format_entries(
    entries: list[dict[str, Any]], data: DataSettings, style: JsonStyle, layout: DataFormat
) -> str:
    """A data file: an array of entries (each keeps its id field), or an object keyed by id."""
    if layout == "array":
        return format_json(entries, style)
    keyed = {
        entry[data.id_field]: {k: v for k, v in entry.items() if k != data.id_field}
        for entry in entries
    }
    return format_json(keyed, style)
