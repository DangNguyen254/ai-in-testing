"""Data-file conventions shared by the indexer, the generator and the validators.

Defaults row: some suites start a data file (array layout) with an entry that has no id field.
Its values apply to every other entry in the file, so a key a test reads may live there instead
of in the test's own entry. ``data.defaults_row`` turns the detection on; ``data.defaults_merge``
says how the suite's loader combines the two (``shallow``: top-level keys; ``shallow_if_set``:
top-level keys whose entry value is set, so an empty or false value keeps the default;
``deep``: nested objects merged key by key).

Per-function data files: some areas keep one data file per test function, named after it, next
to the test module, instead of one file per module (``index.function_data_files``).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, Literal

from ticket2test.config import DataSettings, IndexSettings

Layout = Literal["module", "function"]


def is_defaults_row(entry: Any, id_field: str) -> bool:
    return isinstance(entry, dict) and id_field not in entry


def split_defaults(rows: list[Any], data: DataSettings) -> tuple[dict[str, Any] | None, list[Any]]:
    """(defaults row or None, the other rows). Only the first row can be the defaults row."""
    if data.defaults_row and rows and is_defaults_row(rows[0], data.id_field):
        return rows[0], rows[1:]
    return None, rows


def merged(
    entry: dict[str, Any], defaults: dict[str, Any] | None, data: DataSettings
) -> dict[str, Any]:
    """The entry as the suite's loader sees it: defaults first, the entry's own values win."""
    if not defaults:
        return entry
    if data.defaults_merge == "shallow":
        return {**defaults, **entry}
    if data.defaults_merge == "shallow_if_set":  # an empty or false value keeps the default
        return {**defaults, **{k: v for k, v in entry.items() if v or k not in defaults}}
    return _deep(defaults, entry, depth=0)


def _deep(base: dict[str, Any], over: dict[str, Any], depth: int) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if depth < 32 and isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep(out[key], value, depth + 1)
        else:
            out[key] = value
    return out


def module_data_path(test_file: str, settings: IndexSettings) -> str:
    return str(PurePosixPath(test_file).with_suffix(settings.data_file_suffix))


def function_data_path(test_file: str, function: str, settings: IndexSettings) -> str:
    return str(PurePosixPath(test_file).parent / f"{function}{settings.data_file_suffix}")


def function_data_matches(
    test_file: str, function: str, names: Iterable[str], settings: IndexSettings
) -> list[str]:
    """The function's data files among ``names`` (file names in the test's folder): its own
    file first, then, with ``index.function_data_prefix``, every ``<function>*`` file by name.
    The module's own data file never counts."""
    suffix = settings.data_file_suffix
    module = PurePosixPath(module_data_path(test_file, settings)).name
    own = f"{function}{suffix}"
    names = list(names)
    found = [n for n in names if n == own]
    if settings.function_data_prefix:
        found += sorted(
            n for n in names if n != own and n.startswith(function) and n.endswith(suffix)
        )
    folder = PurePosixPath(test_file).parent
    return [str(folder / n) for n in found if n != module]


def layout_of(
    test_file: str, function: str, data_file: str | None, settings: IndexSettings
) -> Layout:
    """How an existing test keeps its data: in a file named after the function, or the module."""
    if data_file and data_file == function_data_path(test_file, function, settings):
        return "function"
    if data_file and settings.function_data_prefix:
        path, folder = PurePosixPath(data_file), PurePosixPath(test_file).parent
        own = PurePosixPath(module_data_path(test_file, settings))
        if path.parent == folder and path.name.startswith(function) and path != own:
            return "function"
    return "module"
