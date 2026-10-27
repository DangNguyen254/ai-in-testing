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


def _python3(path: Path) -> bool:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    except SyntaxError:
        return False  # v6: a Python 2 leftover, not collected
    return True


@pytest.mark.parametrize(
    "path", [p for p in sorted((STANDIN / "tests").rglob("test_*.py")) if _python3(p)]
)
def test_standin_tests_are_a_fixed_point(path: Path) -> None:
    """The stand-in's own style equals the configured defaults; v7's older report file keeps
    its own style (4-space indent, single quotes) and is a fixed point of that."""
    from ticket2test.style.local import detect_python_style

    code = path.read_text(encoding="utf-8")
    style = Settings().style.python
    if path.name == "test_reports_list.py":
        style = detect_python_style(code, style)
        assert (style.indent_width, style.quote_style) == (4, "single")
    assert format_python(code, style, FIRST_PARTY) == code


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


def test_a_target_python_version_rejects_newer_syntax() -> None:
    """The real suite runs on an older Python than this tool: generated code must parse with
    that version's grammar, and the formatter must not introduce newer syntax."""
    from ticket2test.style.python import target_syntax_error

    match_code = "def f(x):\n   match x:\n      case 1:\n         return 1\n"
    assert target_syntax_error(match_code, "3.8") is not None
    assert target_syntax_error(match_code, "3.10") is None
    assert target_syntax_error(match_code, None) is None
    assert target_syntax_error("def f(a, /, b):\n   return (c := a)\n", "3.8") is None
    style = Settings().style.python.model_copy(update={"target_version": "3.8"})
    assert format_python("x = 1\n", style, FIRST_PARTY) == "x = 1\n"
