"""Per-test JSON data.

Every ``test_<area>.py`` has a ``test_<area>.json`` next to it. Entries are keyed by the
pytest-generated test name, including parametrize ids, e.g. ``test_create_item[1]``.
With stacked parametrize decorators, the bottom decorator's id comes first:
``test_x[<bottom>-<top>]``.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any


def data_file_for(test_file: Path) -> Path:
    return test_file.with_suffix(".json")


@cache
def load_entries(data_file: Path) -> dict[str, dict[str, Any]]:
    if not data_file.is_file():
        return {}
    data: dict[str, dict[str, Any]] = json.loads(data_file.read_text(encoding="utf-8"))
    return data


def entry_for(test_file: Path, test_name: str) -> dict[str, Any] | None:
    return load_entries(data_file_for(test_file)).get(test_name)
