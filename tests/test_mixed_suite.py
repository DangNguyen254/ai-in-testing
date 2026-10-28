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
    legacy = settings.generate.reuse.model_copy(update={"legacy_domains": ["exceptions", "units"]})
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


# --- Phase 4: reviewer warnings for risky patterns -----------------------------------------------


def _risky(report: Any) -> list[str]:
    return [f.message for f in report.findings if f.check == "risky" and f.severity == "warning"]


@pytest.mark.parametrize(
    ("snippet", "words"),
    [
        ("self.test_rules_other()", "calls another test"),
        ("global COUNT", "module globals"),
        ("self.__class__.shared = 1", "class-level state"),
        ("type(self).shared = 1", "class-level state"),
        ("try:\n         rules.search()\n      except Exception:\n         pass", "broad except"),
        ("try:\n         rules.search()\n      except:\n         pass", "broad except"),
    ],
)
def test_risky_patterns_are_flagged_for_the_reviewer(setup: Any, snippet: str, words: str) -> None:
    code = GOOD_CODE.replace("rules.search()", f"rules.search()\n      {snippet}", 1)
    messages = _risky(_validate(setup, code=code))
    assert any(words in m for m in messages), messages


def test_the_good_test_has_no_risky_patterns(setup: Any) -> None:
    assert _risky(_validate(setup)) == []


def test_values_hooks_build_code_from_are_flagged(setup: Any) -> None:
    from tests.test_validate import GOOD_ENTRY

    code = GOOD_CODE.replace('suite("regression")', """suite("regre'ssion")""", 1)
    assert any("marker value" in m for m in _risky(_validate(setup, code=code)))
    entry = {**GOOD_ENTRY, "skip": 'bug "X-1"'}
    assert any("'skip' value" in m for m in _risky(_validate(setup, entries=[entry])))


def test_an_entry_copied_from_its_template_is_flagged(setup: Any) -> None:
    from ticket2test.models.generated import GeneratedTest, TemplateEntryRef
    from ticket2test.validate.validator import validate_generated

    settings, index, roots = setup
    chunk = next(c for c in index.chunks if c.kind == "test" and c.data_entries)
    key, template = next(iter(chunk.data_entries.items()))
    copy = {**template, "test_id": "test_rules_list_filter_next_page"}
    generated = GeneratedTest(
        code=GOOD_CODE,
        file_name="tests/rules/test_rules_list_filter.py",
        data_file_name="tests/rules/test_rules_list_filter.json",
        data_entries=[copy],
        data_format="array",
        test_ids=["test_rules_list_filter_next_page"],
        template_entry_ref=TemplateEntryRef(chunk_id=chunk.id, entry_key=key),
        ticket_id="STND-106",
        draft_ref="STND-106/d1",
        retrieved_chunk_ids=[],
        prompt_version="test",
        provider="fake",
        model="fake",
        attempts=1,
        context_tokens=0,
    )
    report = validate_generated(generated, index.catalog, settings, roots, index=index)
    assert any(f"a copy of {key}" in m for m in _risky(report))


# --- Phase 5: eval pairs without git history ----------------------------------------------------


def test_pairs_come_from_skips_in_the_current_tree(setup: Any, tmp_path: Path) -> None:
    from ticket2test.eval.mining import CURRENT_TREE, mine_current_skips

    settings, index, _ = setup
    files = sorted({c.file_path for c in index.chunks if c.kind == "test"})
    mined = mine_current_skips(STANDIN, files, settings)
    by_ticket = {(m.ticket, m.kind) for m in mined}
    assert ("STND-105", "data_skip") in by_ticket  # an entry's skip cites the ticket
    assert all(m.subject == CURRENT_TREE and m.commit == "" for m in mined)
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_a.py").write_text(
        "import pytest\n\n\nclass TestA:\n"
        '   @pytest.mark.skip(reason="ABC-12: broken")\n'
        "   def test_one(self):\n      pass\n\n   def test_two(self):\n      pass\n",
        encoding="utf-8",
    )
    found = mine_current_skips(repo, ["tests/test_a.py"], settings)
    assert [(m.ticket, m.test, m.kind) for m in found] == [
        ("ABC-12", "tests/test_a.py::TestA::test_one", "code_skip")
    ]


def test_an_import_a_new_method_needs_is_merged_into_the_files_imports(setup: Any) -> None:
    """Found on the investigator run (v6 STND-135): a new method's decorator needed a name the
    file didn't import, and the splice added a second, unsorted import of the same module, so
    the style check failed where no repair could fix it. Only the import block is sorted."""
    from ticket2test.generate.patch import validate_patch

    settings, index, _ = setup
    path = "tests/files/test_files_archives.py"
    code = GENERATED_CLASS.replace(
        "from framework.base_test import BaseTest\n",
        "from framework.base_test import BaseTest\n"
        "from framework.decorators import browsers, cloud_only, data_driven, environments\n",
    ).replace(
        '   @pytest.mark.suite("regression")\n',
        '   @pytest.mark.suite("regression")\n   @cloud_only\n',
    )
    base = next(
        e
        for c in index.chunks
        if c.symbol_name == "test_files_archive_view_members"
        for e in c.data_entries.values()
    )
    kept = {k: v for k, v in base.items() if k not in ("decision", "targets")}
    entry = {**kept, "test_id": "test_files_archive_encrypted_members", "members": ["a.txt"]}
    generated = method_patch(
        _generated(code, [entry]),
        _decision("method", "TestFilesArchives", path),
        index,
        settings,
        STANDIN,
    )
    imports = [line for line in generated.code.splitlines() if "framework.decorators" in line]
    assert imports == [
        "from framework.decorators import browsers, cloud_only, data_driven, environments"
    ]
    source = (STANDIN / path).read_text(encoding="utf-8")
    body = source.split("\n\n\n", 1)[1]  # everything after the imports is kept as it was
    assert body.rstrip("\n") in generated.code
    report = validate_patch(generated, index, settings, STANDIN)
    assert not [f for f in report.errors if f.check == "style"], [f.render() for f in report.errors]


def test_raw_driver_expressions_may_use_a_wildcard(setup: Any) -> None:
    """Real suites wrap the driver: only raw locator calls count, not the wrapper itself."""
    settings = _with(setup[0], "validation", raw_driver_access=["self.driver.find_element*"])
    raw = GOOD_CODE.replace(
        "rules.search()", "rules.search()\n      self.driver.find_elements_by_css('x')", 1
    )
    assert _messages(_validate(setup, code=raw, settings=settings), "raw_driver")
    wrapper = GOOD_CODE.replace("rules.search()", "rules.search()\n      self.driver.get('x')", 1)
    assert not _messages(_validate(setup, code=wrapper, settings=settings), "raw_driver")


# --- real-suite round 3: how tests read their data ----------------------------------------------


def _use(body: str) -> Any:
    from ticket2test.generate.inspect import data_use

    code = "def test_x(self):\n" + "".join(f"    {line}\n" for line in body.splitlines())
    return data_use(code, ["self.params"], ["self.*validate_result", "*.validate_api_response"])[
        "test_x"
    ]


def test_expectation_helpers_may_be_patterns() -> None:
    assert _use("self._area_validate_result()").helpers == {"self._area_validate_result"}
    assert _use("pm.validate_api_response(x)").helpers == {"pm.validate_api_response"}
    assert not _use("self.other()").helpers


def test_a_test_passing_its_whole_entry_on_reads_any_key() -> None:
    from ticket2test.models.generated import unconsumed_keys

    use = _use("runner.run(self.params)")
    assert use.passes_whole
    ctx: dict[str, Any] = {"id_field": "test_id", "expectation_sections": {"targets": ["x"]}}
    entry = {"test_id": "t", "note": 1, "targets": []}
    assert unconsumed_keys(entry, use, ctx) == ({}, "")
    assert unconsumed_keys(entry, _use("x = 1"), ctx)[0]  # without it: both unread


def test_a_key_read_after_a_check_is_optional() -> None:
    use = _use('if "mode" in self.params:\n    x = self.params["mode"]\ny = self.params["name"]')
    assert use.keys == {"name"} and "mode" in use.optional_keys
    use = _use('if self.params.get("mode"):\n    x = self.params["mode"]')
    assert not use.keys and use.optional_keys == {"mode"}


def test_sections_may_list_several_helpers(setup: Any) -> None:
    settings = _with(
        setup[0],
        "data",
        expectation_sections={"targets": ["self.verify_targets", "self.*_validate_result"]},
    )
    assert settings.data.section_helpers() == {
        "targets": ["self.verify_targets", "self.*_validate_result"]
    }
    assert settings.data.helper_patterns() == ["self.verify_targets", "self.*_validate_result"]


def test_a_functions_own_data_file_may_hold_its_cases(tmp_path: Path) -> None:
    """Found on the real suite: the framework runs a test once per entry of the function's own
    data file, with the id ``function[<entry id>]``; entries name only the case."""
    repo = tmp_path / "repo"
    (repo / "tests" / "area").mkdir(parents=True)
    (repo / "tests" / "area" / "test_a.py").write_text(
        "from framework.base import Base\n\n\nclass TestA(Base):\n"
        '   def test_one(self):\n      self.check.assertEqual(1, self.params["k"])\n',
        encoding="utf-8",
    )
    rows = [{"test_id": "small", "k": 1}, {"test_id": "large", "k": 2}]
    (repo / "tests" / "area" / "test_one.json").write_text(json.dumps(rows), encoding="utf-8")
    settings = Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "index": {"function_file_cases": True},
            "validation": {"base_classes": []},
        }
    )
    index, _, _ = update_index(repo, settings)
    chunk = next(c for c in index.chunks if c.kind == "test")
    assert chunk.test_ids == ["test_one[small]", "test_one[large]"]
    assert set(chunk.data_entries) == {"test_one[small]", "test_one[large]"}
    from ticket2test.validate.suite import file_findings

    report = file_findings(repo, "tests/area/test_a.py", index, settings)
    assert [f.message for f in report.findings if f.check == "ids"] == []


def test_a_suites_loader_may_find_function_data_files_by_prefix(tmp_path: Path) -> None:
    """Found on the real suite: the loader takes every ``<function>*.json`` next to the module,
    merges their entries, and uses the module's file only when none matches."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_a.py").write_text(
        "from framework.base import Base\n\n\nclass TestA(Base):\n"
        '   def test_one(self):\n      self.check.assertEqual(1, self.params["k"])\n\n'
        '   def test_two(self):\n      self.check.assertEqual(1, self.params["k"])\n',
        encoding="utf-8",
    )
    files = {
        "test_one_small.json": [{"test_id": "small", "k": 1}],
        "test_one_large.json": [{"test_id": "large", "k": 2}],
        "test_a.json": [{"test_id": "test_two", "k": 3}],
    }
    for name, rows in files.items():
        (repo / "tests" / name).write_text(json.dumps(rows), encoding="utf-8")
    settings = Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "index": {"function_file_cases": True, "function_data_prefix": True},
            "validation": {"base_classes": []},
        }
    )
    index, _, _ = update_index(repo, settings)
    by_name = {c.symbol_name: c for c in index.chunks if c.kind == "test"}
    assert by_name["test_one"].test_ids == ["test_one[large]", "test_one[small]"]
    assert by_name["test_two"].test_ids == ["test_two"]  # no match: the module's file
    from ticket2test.validate.suite import file_findings

    report = file_findings(repo, "tests/test_a.py", index, settings)
    assert [f.message for f in report.findings if f.check == "ids"] == []


def test_what_setup_reads_or_calls_counts_for_every_test(tmp_path: Path) -> None:
    """Found on the real suite: a class's setup calls the helper that applies a section, so
    the tests never call it themselves."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_a.py").write_text(
        "from framework.base import Base\n\n\nclass TestA(Base):\n"
        "   def setup(self):\n      self.apply_policy()\n\n"
        "   def apply_policy(self):\n      pass\n\n"
        '   def test_one(self):\n      self.check.assertEqual(1, self.params["k"])\n',
        encoding="utf-8",
    )
    rows = [{"test_id": "test_one", "k": 1, "policy": {}}]
    (repo / "tests" / "test_a.json").write_text(json.dumps(rows), encoding="utf-8")
    settings = Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "data": {"seed_sections": [], "expectation_sections": {"policy": "self.apply_*"}},
            "validation": {"base_classes": []},
        }
    )
    index, _, _ = update_index(repo, settings)
    from ticket2test.validate.suite import file_findings

    report = file_findings(repo, "tests/test_a.py", index, settings)
    assert [f.message for f in report.findings if f.check == "data_keys"] == []


def _suite_findings(tmp_path: Path, files: dict[str, str], config: dict[str, Any]) -> list[Any]:
    repo = tmp_path / "repo"
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path / "cache")}, "validation": {"base_classes": []}}
        | config
    )
    index, _, _ = update_index(repo, settings)
    from ticket2test.validate.suite import file_findings

    return file_findings(repo, "tests/test_a.py", index, settings).findings


def test_keys_read_by_a_repo_function_the_entry_or_self_is_handed_to(tmp_path: Path) -> None:
    """Found on the real suite: tests hand the entry, or themselves, to a helper module that
    reads the keys; the tool saw only "passes the whole entry" or nothing at all."""
    files = {
        "helpers/checks.py": (
            "def run(entry):\n   return entry['a']\n\n\n"
            "def check(test):\n   return test.params.get('b')\n"
        ),
        "tests/test_a.py": (
            "from framework.base import Base\nfrom helpers import checks\n\n\n"
            "class TestA(Base):\n"
            "   def test_one(self):\n"
            "      checks.run(self.params)\n      checks.check(self)\n"
            "      self.check.assertTrue(True)\n"
        ),
        "tests/test_a.json": json.dumps([{"test_id": "test_one", "a": 1, "b": 2, "c": 3}]),
    }
    found = _suite_findings(tmp_path, files, {"data": {"seed_sections": []}})
    messages = [f.message for f in found if f.check == "data_keys"]
    assert len(messages) == 1 and "'c'" in messages[0] and "'a'" not in messages[0]


def test_a_local_variable_named_like_the_entry_is_not_the_entry(tmp_path: Path) -> None:
    files = {
        "tests/test_a.py": (
            "def test_one(params):\n"
            "   block = params['block']\n   params = block\n   assert params['inner']\n"
        ),
        "tests/test_a.json": json.dumps([{"test_id": "test_one", "block": {"inner": 1}}]),
    }
    found = _suite_findings(tmp_path, files, {"data": {"access": ["params"]}})
    assert not [f.message for f in found if f.check == "data_keys"]


def test_other_assertion_objects_and_classes_without_a_base(tmp_path: Path) -> None:
    files = {
        "framework/base.py": "class Base:\n   pass\n",
        "tests/test_a.py": (
            "import unittest\nfrom framework.base import Base\n\n"
            "check = unittest.TestCase()\n\n\n"
            "class TestA:\n   def test_one(self):\n      check.assertEqual(1, 1)\n\n\n"
            "class TestB(Base):\n   def test_two(self):\n      pass\n"
        ),
    }
    config = {
        "validation": {
            "base_classes": ["Base"],
            "extra_assertion_objects": ["check"],
            "baseless_classes": True,
        }
    }
    found = _suite_findings(tmp_path, files, config)
    assertions = [(f.test, f.message) for f in found if f.check == "assertions"]
    assert [t for t, _ in assertions] == ["test_two"]  # test_one's check counts
    assert not [f for f in found if f.check == "base_class"]


def test_checks_in_teardown_and_autouse_fixtures_count(tmp_path: Path) -> None:
    files = {
        "tests/test_a.py": (
            "import pytest\nfrom framework.base import Base\n\n\n"
            "class TestA(Base):\n"
            "   @pytest.fixture(autouse=True)\n   def seed(self):\n"
            "      self.apply_policy()\n      yield\n\n"
            "   def apply_policy(self):\n      pass\n\n"
            "   def teardown(self):\n      self.check.assertTrue(self.done)\n\n"
            "   def test_one(self):\n      self.done = True\n"
        ),
        "tests/test_a.json": json.dumps([{"test_id": "test_one", "policy": {}}]),
    }
    config = {"data": {"seed_sections": [], "expectation_sections": {"policy": "self.apply_*"}}}
    found = _suite_findings(tmp_path, files, config)
    assert not [f.message for f in found if f.check in ("assertions", "data_keys")]


def test_a_base_setup_called_by_name_reads_for_every_test(tmp_path: Path) -> None:
    """Found on the real suite: ``Base.setup(self)`` (or ``super().setup()``) in the class's
    setup, and the base's setup reads a key behind a presence check."""
    files = {
        "framework/mock.py": (
            "class BaseMock:\n   def setup(self):\n"
            "      if 'body' in self.params:\n         self.payload = self.params['body']\n"
        ),
        "tests/test_a.py": (
            "from framework.mock import BaseMock\n\n\nclass TestA(BaseMock):\n"
            "   def setup(self):\n      BaseMock.setup(self)\n\n"
            "   def test_one(self):\n      self.check.assertTrue(True)\n\n\n"
            "class TestB(BaseMock):\n   def setup(self):\n      super().setup()\n\n"
            "   def test_two(self):\n      self.check.assertTrue(True)\n"
        ),
        "tests/test_a.json": json.dumps(
            [{"test_id": "test_one", "body": {}}, {"test_id": "test_two", "body": {}}]
        ),
    }
    found = _suite_findings(tmp_path, files, {"data": {"seed_sections": []}})
    assert not [f.message for f in found if f.check == "data_keys"]


def test_retired_tests_and_a_function_named_like_its_module(tmp_path: Path) -> None:
    """Found on the real suite: a test switched off with ``skipif(True, ...)`` keeps old data;
    ``test_x.py::test_x`` keeps its cases in ``test_x.json``, the module's own file."""
    files = {
        "tests/test_a.py": (
            "import pytest\n\n\nclass TestA:\n"
            "   @pytest.mark.skipif(True, reason='X-1')\n"
            "   def test_old(self):\n      pass\n\n"
            "   def test_a(self, params):\n"
            "      try:\n         if params['skip']:\n            pytest.skip()\n"
            "      except KeyError:\n         pass\n"
            "      self.check.assertEqual(1, params['k'])\n"
        ),
        "tests/test_a.json": json.dumps(
            [{"test_id": "case_a", "k": 1}, {"test_id": "case_b", "k": 2}]
        ),
    }
    config = {
        "index": {"function_file_cases": True},
        "data": {"access": ["self.params", "params"]},
    }
    found = _suite_findings(tmp_path, files, config)
    assert not [f.message for f in found if f.check in ("ids", "data_keys")]


def test_a_module_level_testcase_and_an_entry_copied_in_a_helper(tmp_path: Path) -> None:
    """Found on the real suite: a file's own ``tc = unittest.TestCase(...)`` does the checks;
    a helper builds a new dict from the entry and reads the keys from it."""
    files = {
        "framework/run.py": (
            "def resolve(env, params):\n   return dict(params)\n\n\n"
            "def run_helper(env, params):\n   row = resolve(env, params)\n"
            "   spec = row.get('a', {})\n   for step in row.get('b', []):\n      pass\n"
        ),
        "tests/test_a.py": (
            "import unittest\nfrom framework.run import run_helper\n\n"
            "tc = unittest.TestCase('__init__')\n\n\n"
            "class TestA:\n   def test_one(self, params, env):\n"
            "      run_helper(env, params)\n      tc.assertTrue(True)\n"
        ),
        "tests/test_a.json": json.dumps([{"test_id": "test_one", "a": {}, "b": [], "c": 1}]),
    }
    config = {"data": {"access": ["self.params", "params"], "seed_sections": []}}
    found = _suite_findings(tmp_path, files, config)
    assert not [f for f in found if f.check == "assertions"]
    messages = [f.message for f in found if f.check == "data_keys"]
    assert len(messages) == 1 and "'c'" in messages[0] and "'a'" not in messages[0]


def test_a_name_rebound_from_a_call_given_the_entry_is_read_not_required(tmp_path: Path) -> None:
    files = {
        "tests/test_a.py": (
            "def block_of(params, name):\n   return params[name]\n\n\n"
            "def test_one(params):\n"
            "   params = block_of(params, 'block')\n   assert params['inner']\n"
        ),
        "tests/test_a.json": json.dumps([{"test_id": "test_one", "block": {"inner": 1}}]),
    }
    found = _suite_findings(tmp_path, files, {"data": {"access": ["params"]}})
    assert not [f.message for f in found if f.check == "data_keys" and "lacks" in f.message]
