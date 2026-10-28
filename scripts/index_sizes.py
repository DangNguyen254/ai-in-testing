"""Where the saved index's bytes go, by section and by field, without loading it whole.

Usage: python scripts/index_sizes.py <path to index.json>

Prints only the tool's own field names and sizes (no names from the indexed repo), so the
output can be shared. Memory: the file as one string plus one record at a time.
"""

from __future__ import annotations

import json
import sys
from collections import Counter

_DECODER = json.JSONDecoder()


def _skip_ws(text: str, at: int) -> int:
    while text[at] in " \t\r\n":
        at += 1
    return at


def _top_level(text: str) -> dict[str, tuple[int, int]]:
    """Top-level key -> (start, end) of its value."""
    spans: dict[str, tuple[int, int]] = {}
    at = _skip_ws(text, 0) + 1  # past "{"
    while True:
        at = _skip_ws(text, at)
        if text[at] == "}":
            return spans
        key, at = _DECODER.raw_decode(text, at)
        at = _skip_ws(text, at) + 1  # past ":"
        start = _skip_ws(text, at)
        end = _value_end(text, start)
        spans[key] = (start, end)
        at = _skip_ws(text, end)
        if text[at] == ",":
            at += 1


def _value_end(text: str, start: int) -> int:
    """End of the JSON value at ``start``, by bracket matching (strings skipped)."""
    if text[start] not in "[{":
        return _DECODER.raw_decode(text, start)[1]
    depth, at, in_string = 0, start, False
    while True:
        ch = text[at]
        if in_string:
            if ch == "\\":
                at += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return at + 1
        at += 1


def _items(text: str, start: int, end: int, is_object: bool):  # type: ignore[no-untyped-def]
    """Each element of the array (or each value of the object) at text[start:end]."""
    at = start + 1
    while True:
        at = _skip_ws(text, at)
        if at >= end - 1 or text[at] in "]}":
            return
        if is_object:
            _, at = _DECODER.raw_decode(text, at)
            at = _skip_ws(text, at) + 1
            at = _skip_ws(text, at)
        value, at = _DECODER.raw_decode(text, at)
        yield value
        at = _skip_ws(text, at)
        if text[at] == ",":
            at += 1


def _size(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":")))


def main(path: str) -> None:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    total = len(text)
    spans = _top_level(text)
    print(f"index: {total / 1e6:.1f} MB")
    for key, (start, end) in spans.items():
        print(f"  {key}: {(end - start) / 1e6:.1f} MB ({(end - start) / total:.0%})")

    if "chunks" in spans:
        fields: Counter[str] = Counter()
        kinds: Counter[str] = Counter()
        for chunk in _items(text, *spans["chunks"], is_object=False):
            kinds[chunk.get("kind", "?")] += 1
            for name, value in chunk.items():
                fields[name] += _size(value)
        print(f"  chunks by kind: {dict(kinds)}")
        for name, size in fields.most_common(6):
            print(f"    chunks.{name}: {size / 1e6:.1f} MB")

    if "files" in spans:
        fields = Counter()
        for record in _items(text, *spans["files"], is_object=True):
            info = record.get("info") or {}
            for name, value in info.items():
                if name in ("classes", "functions"):
                    code = sum(len(x.get("code", "")) for x in value)
                    methods = sum(
                        len(m.get("code", "")) for x in value for m in x.get("methods", [])
                    )
                    fields[f"{name} (code)"] += code
                    fields[f"{name} (method code)"] += methods
                    fields[f"{name} (rest)"] += _size(value) - code - methods
                else:
                    fields[name] += _size(value)
        for name, size in fields.most_common(8):
            print(f"    files.info.{name}: {size / 1e6:.1f} MB")

    if "catalog" in spans:
        start, end = spans["catalog"]
        catalog = _DECODER.raw_decode(text, start)[0]
        sizes = Counter({name: _size(value) for name, value in catalog.items()})
        for name, size in sizes.most_common(5):
            print(f"    catalog.{name}: {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1])
