"""check-suite: calibrating the config against an existing suite (no container needed here)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.index.indexer import update_index
from ticket2test.sandbox.runner import SuiteCollect
from ticket2test.validate import suite as suite_module
from ticket2test.validate.suite import check_suite, render_markdown

STANDIN = Path(__file__).resolve().parents[1] / "standin"


def _settings(tmp_path: Path, **sections: Any) -> Settings:
    return Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}, **sections})


def test_the_standin_is_clean_with_its_own_config(tmp_path: Path) -> None:
    report = check_suite(STANDIN, _settings(tmp_path))
    assert report.ok and report.errors == 0 and report.by_check == []
    assert report.test_files == 20 and report.tests == 113  # v7: the legacy units file skipped
    assert report.legacy_files == 1
    assert {(d.area, d.check) for d in report.deviations} == {
        ("reports", "raw_driver"),  # older report tests: deviations, not config errors
        ("reports", "star_imports"),
    }
    # framework/base_test.py matches the "*_test.py" glob but has no tests: not checked.
    assert report.clean_files == report.test_files
    assert "**clean**" in render_markdown(report)


def test_a_wrong_config_is_reported_by_check_with_the_keys_to_fix(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        markers={"priorities": ["P0", "P1", "P2", "P3"]},
        style={"python": {"indent_width": 4}, "json": {"indent": 2}, "follow_local": False},
        validation={"base_classes": ["SuiteBase"]},
    )
    report = check_suite(STANDIN, settings)
    assert not report.ok
    by_check = {s.check: s for s in report.by_check}
    assert {"markers", "style", "data_file", "base_class"} <= set(by_check)
    assert "markers.priorities" in by_check["markers"].hint
    assert "style.python" in by_check["style"].hint
    assert "style.json" in by_check["data_file"].hint
    assert any("priority value 'p2' is not approved" in e for e in by_check["markers"].examples)
    assert by_check["base_class"].files == 20
    markdown = render_markdown(report)
    assert "config needs changes" in markdown and "| markers |" in markdown


def test_ids_are_compared_with_a_real_collect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    index, _, _ = update_index(STANDIN, settings)
    static = sorted(
        f"{c.file_path}::{cls}::{t}"
        for c in index.chunks
        if c.kind == "test"
        for cls in c.collected_classes or [c.class_name]
        for t in c.test_ids
    )
    collected = [n for n in static if "test_rules_list_empty" not in n]
    collected.append("tests/rules/test_rules.py::TestRules::test_rules_extra")

    def fake_collect(repo: Path, settings: Settings, **_: Any) -> SuiteCollect:
        return SuiteCollect(exit_code=0, duration_seconds=0.1, node_ids=collected)

    monkeypatch.setattr(suite_module, "collect_suite", fake_collect)
    report = check_suite(STANDIN, settings, collect=True)
    assert report.ids.ran and report.ids.static == 116 and report.ids.collected == 116
    assert report.ids.only_static == ["tests/rules/test_rules.py::TestRules::test_rules_list_empty"]
    assert report.ids.only_collected == ["tests/rules/test_rules.py::TestRules::test_rules_extra"]
    assert not report.ok  # validators are clean, but the ids disagree


def test_cli_check_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T2T_PATHS__CACHE_DIR", str(tmp_path / "cache"))
    runner = CliRunner()
    out = tmp_path / "reports"
    result = runner.invoke(app, ["check-suite", str(STANDIN), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert list(out.glob("check-suite-*.md")) and list(out.glob("check-suite-*.json"))
    monkeypatch.setenv("T2T_STYLE__PYTHON__INDENT_WIDTH", "4")
    result = runner.invoke(app, ["check-suite", str(STANDIN), "--out", str(out)])
    assert result.exit_code == 0  # each file is judged in its own style (style.follow_local)
    monkeypatch.setenv("T2T_STYLE__FOLLOW_LOCAL", "false")
    result = runner.invoke(app, ["check-suite", str(STANDIN), "--out", str(out)])
    assert result.exit_code == 1 and "style.python" in result.output
    result = runner.invoke(app, ["check-suite", str(tmp_path / "missing")])
    assert result.exit_code == 2


def test_the_json_report_says_whether_it_is_clean(tmp_path: Path) -> None:
    import json

    report = check_suite(STANDIN, _settings(tmp_path))
    data = json.loads(report.model_dump_json())
    assert data["ok"] is True and data["errors"] == 0


def test_message_patterns_mask_the_suites_names(tmp_path: Path) -> None:
    """Calibrating against a private suite: the patterns can be shared, the examples can't."""
    from ticket2test.validate.suite import mask_message

    assert mask_message("priority value 'P1' is not approved (known: p0, p1)") == (
        "priority value '...' is not approved (known: p0, p1)"
    )
    assert mask_message("missing @pytest.mark.suite(...)") == "missing @pytest.mark.suite(...)"
    assert mask_message("class TestFooBar must inherit one of BaseTest") == (
        "class <Name> must inherit one of <Name>"
    )
    assert mask_message("acme.pages.cart has no name 'Cart' (tests/a/test_b.py, line 12)") == (
        "<a.b> has no name '...' (<path>, line N)"
    )
    settings = _settings(tmp_path, markers={"priorities": ["P0", "P1", "P2", "P3"]})
    report = check_suite(STANDIN, settings)
    markers = next(s for s in report.by_check if s.check == "markers")
    assert markers.patterns and markers.patterns[0].endswith(
        "is not approved (known: P0, P1, P2, P3)"
    )
    assert "Message patterns (names masked" in render_markdown(report)
