"""Formatting generated code and data to the suite's style rules (config `style`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import DataSettings, JsonStyle, PythonStyle, Settings
from ticket2test.style import FormatError, format_entries, format_json, format_python
from ticket2test.style.python import strip_annotations

STANDIN = REPO_ROOT / "standin"
FIRST_PARTY = ["app", "framework", "tests"]

MESSY = """from __future__ import annotations
import pytest
from typing import Any
import os
from framework.decorators import data_driven
from framework.base_test import BaseTest


class TestThing(BaseTest):
    count: int
    limit: int = 3

    @pytest.mark.priority("p1")
    def test_thing(self, value: str, *args: Any, size: int = 2, **kw: Any) -> None:
        x: dict[str, Any] = {'a':1}
        self.check.equal(x, {"a": 1}, "x")\r
"""


def test_strip_annotations_keeps_names_defaults_and_layout() -> None:
    out = strip_annotations(MESSY)
    assert "from __future__" not in out
    assert "count: int" not in out and "limit = 3" in out
    assert "def test_thing(self, value, *args, size=2, **kw):" in out
    assert "x = {'a':1}" in out
    assert strip_annotations("def broken(:\n") == "def broken(:\n"  # left for validation


def test_format_python_applies_indent_imports_quotes_and_lf() -> None:
    out = format_python(MESSY, PythonStyle(), FIRST_PARTY)
    lines = out.split("\n")
    assert "\r" not in out and out.endswith("\n")
    assert "   def test_thing(self, value, *args, size=2, **kw):" in lines
    assert '      x = {"a": 1}' in lines
    # Unused imports dropped; stdlib / third-party / first-party groups, alphabetical.
    assert "import os" not in out and "from typing import Any" not in out
    imports = [line for line in lines if line.startswith(("import ", "from "))]
    assert imports == [
        "import pytest",
        "from framework.base_test import BaseTest",
    ]
    assert format_python(out, PythonStyle(), FIRST_PARTY) == out  # idempotent


def test_format_python_follows_config_values() -> None:
    style = PythonStyle(indent_width=4, quote_style="single", strip_annotations=False)
    out = format_python('def f(a: int) -> int:\n  return "x"\n', style, [])
    assert out == "def f(a: int) -> int:\n    return 'x'\n"


def test_format_python_raises_on_broken_code() -> None:
    with pytest.raises(FormatError):
        format_python("def broken(:\n", PythonStyle(strip_annotations=False), [])


@pytest.mark.parametrize("path", sorted((STANDIN / "tests").rglob("test_*.py")))
def test_standin_tests_are_a_fixed_point(path: Path) -> None:
    """The stand-in's own style equals the configured defaults."""
    code = path.read_text(encoding="utf-8")
    assert format_python(code, Settings().style.python, FIRST_PARTY) == code


def test_json_style_matches_the_standin_data_files() -> None:
    style = Settings().style.json_files
    for path in (STANDIN / "tests").rglob("*.json"):
        raw = path.read_text(encoding="utf-8")
        assert format_json(json.loads(raw), style) == raw, path


def test_format_entries_writes_array_or_object_layout() -> None:
    entries = [{"test_id": "test_a[1]", "x": 1}, {"test_id": "test_a[2]", "x": 2}]
    style = JsonStyle(indent=2, key_separator=": ")
    array = format_entries(entries, DataSettings(), style, "array")
    assert json.loads(array) == entries and '"x": 1' in array and array.endswith("\n")
    keyed = json.loads(format_entries(entries, DataSettings(), style, "object"))
    assert keyed == {"test_a[1]": {"x": 1}, "test_a[2]": {"x": 2}}
