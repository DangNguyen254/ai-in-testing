"""Reading a real run's console log (synthetic logs in the real runner's shape)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import REPO_ROOT
from ticket2test.cli import app
from ticket2test.config import ResultsSettings
from ticket2test.models.generated import GeneratedTest
from ticket2test.results.console import RunResult, parse_console, verdict

RUNS = REPO_ROOT / "tests" / "fixtures" / "runs"
CFG = ResultsSettings()


def _log(name: str) -> str:
    return (RUNS / name).read_text(encoding="utf-8")


def test_a_passed_run_with_printed_output_and_warnings() -> None:
    log = parse_console(_log("passed.log"), CFG)
    assert [(r.test_id, r.status) for r in log.results] == [
        ("test_rules_add_basic[allow]", "passed"),  # PASSED on its own line after -s output
        ("test_rules_add_basic[deny]", "passed"),  # PASSED at the end of the node-id line
    ]  # the warnings summary repeats a node id: not a second result
    first = log.results[0]
    assert first.class_name == "TestRules_chrome_latest_Windows_10_cloud_r1"
    assert first.file == "rules/test_rules.py"
    assert log.summary.startswith("2 passed, 38 deselected")


def test_a_failed_run_with_errors_and_links() -> None:
    log = parse_console(_log("failed.log"), CFG)
    by = {(r.class_name, r.test_id): r for r in log.results}
    chrome = "TestRules_chrome_latest_Windows_10_cloud_r1"
    failed = by[(chrome, "test_rules_edit_action")]
    assert failed.status == "failed" and failed.error_type == "AssertionError"
    assert failed.message.startswith("AssertionError: 'deny' != 'allow'")
    assert failed.links == ["https://app.saucelabs.com/tests/4444eeee5555ffff6666aaaa7777bbbb"]
    other = by[("TestRules_firefox_latest_Windows_10_cloud_r1", "test_rules_edit_action")]
    assert other.status == "passed" and other.links == []
    setup_error = by[(chrome, "test_rules_edit_reset")]
    assert setup_error.status == "error" and setup_error.error_type == "KeyError"
    assert setup_error.links == ["https://app.saucelabs.com/tests/0000aaaa1111bbbb2222cccc3333dddd"]


def test_xdist_lines() -> None:
    text = (
        "==== test session starts ====\n"
        "[gw0] [ 50%] PASSED rules/test_rules.py::TestRules::test_a\n"
        "[gw1] [100%] FAILED rules/test_rules.py::TestRules::test_b[x]\n"
        "==== 1 failed, 1 passed in 3.0s ====\n"
    )
    log = parse_console(text, CFG)
    assert [(r.test_id, r.status) for r in log.results] == [
        ("test_a", "passed"),
        ("test_b[x]", "failed"),
    ]


def _r(status: str, error: str | None = None) -> RunResult:
    return RunResult(
        node_id="f.py::T::t", file="f.py", class_name="T", test_id="t",
        status=status, error_type=error,  # type: ignore[arg-type]
    )  # fmt: skip


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([], "not_run"),
        ([_r("passed"), _r("passed")], "passed"),
        ([_r("skipped")], "not_run"),
        ([_r("passed"), _r("failed", "AssertionError")], "check_failed"),
        ([_r("failed", "AttributeError")], "test_problem"),
        ([_r("error", "KeyError")], "test_problem"),
        ([_r("error", "selenium.common.exceptions.NoSuchElementException")], "test_problem"),
        ([_r("error", "RuntimeError")], "error"),
        ([_r("failed", "RuntimeError")], "unclear"),
    ],
)
def test_verdicts(results: list[RunResult], expected: str) -> None:
    assert verdict(results, CFG) == expected


def test_cli_results_records_the_run(tmp_path: Path) -> None:
    generated = GeneratedTest(
        code="",
        file_name="tests/rules/test_rules.py",
        data_file_name="tests/rules/test_rules.json",
        data_entries=[],
        data_format="array",
        test_ids=["test_rules_add_basic[allow]", "test_rules_edit_action"],
        template_entry_ref=None,
        ticket_id="X-1",
        draft_ref="X-1/d1",
        retrieved_chunk_ids=[],
        prompt_version="",
        provider="",
        model="",
        attempts=0,
        context_tokens=0,
        new_test_ids=["test_rules_edit_action"],  # a patch: only the ids it added count
    )
    folder = tmp_path / "gen" / "X-1_d1"
    folder.mkdir(parents=True)
    (folder / "generated.json").write_text(generated.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(app, ["results", str(RUNS / "failed.log"), str(tmp_path / "gen")])
    assert result.exit_code == 0, result.output
    assert "X-1 tests/rules/test_rules.py: check_failed (2 result(s))" in result.output
    assert "https://app.saucelabs.com/tests/4444eeee5555ffff6666aaaa7777bbbb" in result.output
    stored = GeneratedTest.model_validate_json((folder / "generated.json").read_text("utf-8"))
    assert stored.run_report is not None and stored.run_report["verdict"] == "check_failed"
    assert len(stored.run_report["results"]) == 2  # chrome failed, firefox passed
