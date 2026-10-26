"""Phase 2 of the real-suite fit plan: what a mixed, older suite needs before calibration can
come out clean. Correctness rules hold for generated tests (a reviewer note where neighbours
break them), cosmetic rules follow the local style, legacy areas are out of scope, pages built
by constructors are allowed only where the class already builds them."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from tests.test_patch import GENERATED_CLASS, _decision, _generated
from tests.test_validate import GOOD_CODE, _messages, _validate
from ticket2test.config import Settings
from ticket2test.generate.domain import Domain, is_legacy
from ticket2test.generate.patch import method_patch
from ticket2test.generate.reuse import _deployment_gate, _uses_page_objects
from ticket2test.index.datafile import merged
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.generated import unconsumed_keys
from ticket2test.style.local import detect_json_style, detect_python_style, insert_entries
from ticket2test.validate import validator
from ticket2test.validate.suite import check_suite

STANDIN = REPO_ROOT / "standin"


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData, list[str]]:
    from ticket2test.generate.generator import first_party

    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("cache"))}}
    )
    index, _, _ = update_index(STANDIN, settings)
    return settings, index, first_party(index, settings)


def _with(settings: Settings, section: str, **values: Any) -> Settings:
    part = getattr(settings, section).model_copy(update=values)
    return settings.model_copy(update={section: part})


# --- data ---------------------------------------------------------------------------------------


def test_defaults_merge_where_an_empty_value_keeps_the_default() -> None:
    from ticket2test.config import DataSettings

    defaults = {"browser": "chrome", "skip": False, "tags": ["a"]}
    entry = {"test_id": "t", "browser": "", "skip": True, "tags": []}
    plain = merged(entry, defaults, DataSettings(defaults_merge="shallow"))
    assert plain["browser"] == "" and plain["tags"] == []
    if_set = merged(entry, defaults, DataSettings(defaults_merge="shallow_if_set"))
    assert if_set == {"test_id": "t", "browser": "chrome", "skip": True, "tags": ["a"]}


def test_two_expectation_sections_only_when_the_suite_allows_them() -> None:
    class Use:
        keys: frozenset[str] = frozenset()
        optional_keys: frozenset[str] = frozenset()
        helpers = frozenset({"self.verify_targets", "self.verify_interactions"})

    entry = {"test_id": "t", "targets": [], "interactions": []}
    ctx: dict[str, Any] = {
        "id_field": "test_id",
        "expectation_sections": {
            "targets": "self.verify_targets",
            "interactions": "self.verify_interactions",
        },
    }
    assert "one expectation section" in unconsumed_keys(entry, Use(), ctx)[1]
    ctx["allowed_expectation_sets"] = [["targets", "interactions"]]
    assert unconsumed_keys(entry, Use(), ctx) == ({}, "")


# --- unique names, gates, legacy areas ----------------------------------------------------------


def test_each_base_class_has_its_own_unique_name_helper(setup: Any) -> None:
    settings = _with(
        setup[0],
        "validation",
        unique_name_helpers={"BaseTest": "self.unique_name", "OtherBase": "self.short_name"},
    )
    other = GOOD_CODE.replace("rules.search()", "rules.search()\n      self.short_name(10)", 1)
    messages = _messages(_validate(setup, code=other, settings=settings), "names_unique")
    assert any("self.short_name() belongs to another base class" in m for m in messages)
    own = GOOD_CODE.replace("rules.search()", "rules.search()\n      self.unique_name(10)", 1)
    assert not _messages(_validate(setup, code=own, settings=settings), "names_unique")


def test_deployment_gates_written_as_conditions(setup: Any) -> None:
    settings = _with(
        setup[0],
        "generate",
        deployment_decorators={
            "cloud": 'pytest.mark.skipif(OFFSET == 0, reason="cloud only")',
            "on_prem": 'pytest.mark.skipif(OFFSET != 0, reason="on-prem only")',
        },
        deployment_gate_patterns={"on_prem": [r"skipif\(\s*not\s+is_single_tenant"]},
    )
    deployments = ["cloud", "on_prem"]
    written = ['@pytest.mark.skipif( OFFSET == 0,  reason="cloud only")']
    assert _deployment_gate(written, deployments, settings) == {"cloud"}
    pattern = ["pytest.mark.skipif(not is_single_tenant(), reason='x')"]
    assert _deployment_gate(pattern, deployments, settings) == {"on_prem"}
    assert _deployment_gate(["pytest.mark.slow"], deployments, settings) is None


def test_legacy_areas_by_name_or_folder() -> None:
    area = Domain("units", ("tests/units",))
    assert is_legacy(area, ["units"]) and is_legacy(area, ["tests/units"])
    assert is_legacy(area, ["tests/*"]) and not is_legacy(area, ["rules"])


def test_a_legacy_area_only_decides_covered(setup: Any) -> None:
    from tests.test_reuse import SCENARIOS, _empty_retrieval
    from ticket2test.generate.domain import choose_domain
    from ticket2test.generate.reuse import decide

    settings, index, _ = setup
    draft = SCENARIOS["method"][0]
    retrieval = _empty_retrieval()
    choice = choose_domain(retrieval, index, settings, None, draft)
    assert choice.domain is not None
    legacy = settings.generate.reuse.model_copy(update={"legacy_domains": [choice.domain.name]})
    settings = settings.model_copy(
        update={"generate": settings.generate.model_copy(update={"reuse": legacy})}
    )
    decision = decide(draft, retrieval, index, settings, choice)
    assert decision.kind == "out_of_scope"
    assert any("legacy area" in r for r in decision.reasons)
    covered = SCENARIOS["covered"][0]
    assert decide(covered, retrieval, index, settings, choice).kind in ("covered", "out_of_scope")


def test_ui_tests_go_only_into_classes_that_use_page_objects(setup: Any) -> None:
    settings, index, _ = setup
    chunk = next(c for c in index.chunks if c.kind == "test" and "self.nav." in c.code)
    assert chunk.class_name is not None
    assert _uses_page_objects(chunk.file_path, chunk.class_name, index, settings)
    raw = index.model_copy(
        update={
            "chunks": [
                c.model_copy(update={"code": c.code.replace("self.nav.", "self.driver.")})
                if c.file_path == chunk.file_path and c.class_name == chunk.class_name
                else c
                for c in index.chunks
            ]
        }
    )
    assert not _uses_page_objects(chunk.file_path, chunk.class_name, raw, settings)


# --- pages built by constructors ----------------------------------------------------------------

BUILT = GOOD_CODE.replace("rules.search()", "rules.search()\n      RuleListPage(self.driver)", 1)


def test_a_page_built_by_a_constructor_is_an_error_in_a_new_class(setup: Any) -> None:
    report = _validate(setup, code=BUILT, file_name="tests/rules/test_rules_new_area.py")
    found = [f for f in report.findings if f.check == "constructed_pages"]
    assert [f.severity for f in found] == ["error"]
    assert "reach it through the chain root" in found[0].message


def test_it_is_allowed_and_flagged_where_the_class_already_builds_it(
    setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validator, "_class_code", lambda s, cls: "page = RuleListPage(drv)")
    found = [f for f in _validate(setup, code=BUILT).findings if f.check == "constructed_pages"]
    assert [f.severity for f in found] == ["warning"]


# --- local style ----------------------------------------------------------------------------------


def test_the_local_style_is_detected(setup: Any) -> None:
    base = setup[0].style.python
    code = "class A:\n    def f(self):\n        return 'x' + 'y' + \"z\"\n"
    style = detect_python_style(code, base)
    assert (style.indent_width, style.quote_style) == (4, "single")
    text = '[\n  {\n    "test_id": "t",\n    "a": 1\n  }\n]\n'
    json_style = detect_json_style(text, setup[0].style.json_files)
    assert (json_style.indent, json_style.key_separator) == (2, ": ")


def test_entries_are_inserted_without_touching_existing_lines(setup: Any) -> None:
    style = detect_json_style('[\n  {"test_id":"a"}\n]\n', setup[0].style.json_files)
    text = '[\n  {"test_id":"a", "x": [1,2]},\n  {"test_id":"b"}\n]\n'
    after = insert_entries(text, [{"test_id": "c"}], 0, style)
    assert after is not None
    assert after.startswith('[\n  {"test_id":"a", "x": [1,2]},')
    assert after.endswith('  {"test_id":"b"}\n]\n')
    assert json.loads(after) == [{"test_id": "a", "x": [1, 2]}, {"test_id": "c"}, {"test_id": "b"}]
    assert insert_entries('{"t": {}}', [{"test_id": "c"}], None, style) is None  # object layout


def test_a_method_patch_keeps_the_files_own_style(setup: Any, tmp_path: Path) -> None:
    settings, index, _ = setup
    repo = tmp_path / "repo"
    shutil.copytree(STANDIN, repo, ignore=shutil.ignore_patterns(".git"))
    path = "tests/files/test_files_archives.py"
    source = (repo / path).read_text(encoding="utf-8")
    odd = source.replace('"', "'")  # the file uses single quotes; the config says double
    (repo / path).write_text(odd, encoding="utf-8", newline="\n")
    data = repo / path.replace(".py", ".json")
    rows = json.loads(data.read_text(encoding="utf-8"))
    data.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8", newline="\n")
    base = next(
        e
        for c in index.chunks
        if c.symbol_name == "test_files_archive_view_members"
        for e in c.data_entries.values()
    )
    kept = {k: v for k, v in base.items() if k not in ("decision", "targets")}
    entry = {**kept, "test_id": "test_files_archive_encrypted_members", "members": ["a.txt"]}
    generated = method_patch(
        _generated(GENERATED_CLASS, [entry]),
        _decision("method", "TestFilesArchives", path),
        index,
        settings,
        repo,
    )
    assert generated.code.startswith(odd)  # nothing before the new method changed
    added = generated.code[len(odd) :]
    assert "'p2'" in added and '"p2"' not in added  # the new method takes the file's quotes
    removed = [
        line
        for p in generated.patches
        if p.path.endswith(".json")
        for line in p.diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    assert set(removed) <= {"- }"}  # at most the last entry's closing brace gets a comma


# --- check-suite and reviewer notes ---------------------------------------------------------------


def test_check_suite_reports_deviations_and_skips_legacy_areas(setup: Any) -> None:
    settings = _with(setup[0], "validation", raw_driver_access=["self.check"])
    legacy = settings.generate.reuse.model_copy(update={"legacy_domains": ["exceptions"]})
    settings = settings.model_copy(
        update={"generate": settings.generate.model_copy(update={"reuse": legacy})}
    )
    report = check_suite(STANDIN, settings)
    assert report.ok  # deviations are not config errors
    assert report.legacy_files > 0
    areas = {d.area for d in report.deviations if d.check == "raw_driver"}
    assert areas and "exceptions" not in areas


def test_neighbours_that_break_a_rule_give_a_reviewer_note(setup: Any) -> None:
    from ticket2test.generate.pipeline import _neighbour_notes

    settings = _with(setup[0], "validation", raw_driver_access=["self.check"])
    decision = _decision("method", "TestFilesArchives", "tests/files/test_files_archives.py")
    notes = _neighbour_notes(decision, setup[1], settings, STANDIN)
    assert len(notes) == 1 and "drive the browser directly" in notes[0]
    assert _neighbour_notes(decision, setup[1], setup[0], STANDIN) == []
