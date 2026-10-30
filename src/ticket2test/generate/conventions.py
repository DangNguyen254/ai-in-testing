"""Sections every entry of a file has: the suite's data conventions (e.g. a login user, a config
block the framework reads), copied into a new entry by code, never left to the model.

The scope widens until there is enough data: the entries of the target file, then of the tests
in its folder, then of the whole suite. A section counts when at least ``data.convention_share``
of the entries in the scope have it (and the scope has ``data.convention_min_entries``).
``data.required_sections`` are added always. The id field, expectation sections and per-entry
keys are not conventions: they belong to each test.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData


@dataclass
class Conventions:
    scope: str = ""  # "this file", "this folder", "the suite", or "" when none was found
    values: dict[str, Any] = field(default_factory=dict)  # section -> nearest sibling's value

    @property
    def keys(self) -> list[str]:
        return list(self.values)


def convention_sections(test_file: str, index: IndexData, settings: Settings) -> Conventions:
    d = settings.data
    own = {
        d.id_field,
        *d.section_helpers(),
        *d.per_entry_keys,
    }
    folder = str(PurePosixPath(test_file).parent)
    scopes: list[tuple[str, Callable[[str], bool]]] = [
        ("this file", lambda path: path == test_file),
        ("this folder", lambda path: str(PurePosixPath(path).parent) == folder),
        ("the suite", lambda path: True),
    ]
    found = Conventions()
    for name, inside in scopes:
        entries = [
            e
            for c in index.chunks
            if c.kind == "test" and not c.inherited_from and inside(c.file_path)
            for e in c.data_entries.values()
            if isinstance(e, dict)
        ]
        if len(entries) < d.convention_min_entries:
            continue
        counts: dict[str, int] = {}
        for entry in entries:
            for key in entry:
                if key not in own:
                    counts[key] = counts.get(key, 0) + 1
        keys = [k for k, n in counts.items() if n >= d.convention_share * len(entries)]
        found = Conventions(name, {k: _nearest(k, entries) for k in sorted(keys)})
        break
    for key in d.required_sections:
        if key not in found.values:
            entries = [e for c in index.chunks if c.kind == "test" for e in c.data_entries.values()]
            value = _nearest(key, [e for e in entries if isinstance(e, dict)])
            if value is not None:
                found.values[key] = value
                found.scope = found.scope or "the suite"
    return found


def _nearest(key: str, entries: list[dict[str, Any]]) -> Any:
    """The section's value in the first entry (file order) that has it."""
    return next((copy.deepcopy(e[key]) for e in entries if key in e), None)


def with_conventions(
    entry: dict[str, Any], base: dict[str, Any], conventions: Conventions
) -> tuple[dict[str, Any], list[str]]:
    """The entry with every convention section it lacks: from the base entry when it has it,
    else from the nearest sibling entry. Returns the sections added."""
    added: list[str] = []
    result = dict(entry)
    for key, sibling in conventions.values.items():
        if key in result:
            continue
        result[key] = copy.deepcopy(base[key]) if key in base else copy.deepcopy(sibling)
        added.append(key)
    return result, added
