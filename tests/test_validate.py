"""Deterministic validators (Phase 7): a passing and a failing example for each check.

The generated code is parsed, never run. The catalog comes from indexing the stand-in.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ticket2test.config import Settings
from ticket2test.generate.generator import first_party
from ticket2test.generate.inspect import computed_test_ids
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import GeneratedTest
from ticket2test.style import format_entries
from ticket2test.validate.report import ValidationReport
from ticket2test.validate.validator import module_imports, validate_generated

STANDIN = Path(__file__).resolve().parents[1] / "standin"

GOOD_CODE = '''import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("rules")
class TestRulesListFilter(BaseTest):
   def setup(self):
      self.base_setup(fresh_driver=False, policy_wait=True)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_rules_list_filter_next_page(self):
      """
      1. Filter the rule list by the allow action.
      2. Page 1 is full and shows only allow rules.
      3. Go to the next page.
      4. Page 2 shows only allow rules and the allow filter stays selected.
      """
      rules = self.nav.rules.list
      rules.open()
      rules.action_filter = "allow"
      rules.search()

      self.check.assertEqual(self.params["total_count"], rules.total_count)
      self.check.assertEqual(rules.page_size, len(rules.rule_names))
      self.check.assertEqual({"allow"}, set(rules.rule_actions))

      rules.next_page()

      self.check.assertEqual(2, rules.page_number)
      self.check.assertEqual("allow", rules.action_filter)
      self.check.assertEqual(self.params["page_2_names"], rules.rule_names)
      self.check.assertEqual({"allow"}, set(rules.rule_actions))
'''

_RULES = [
    {"name": f"{{test_id:12}}-{n}", "action": a}
    for n, a in [
        ("alpha-web", "allow"), ("alpha-mail", "allow"), ("Alpha-backup", "deny"),
        ("beta-api", "allow"), ("beta-dns", "allow"), ("gamma-ftp", "deny"),
        ("gamma-ssh", "allow"), ("epsilon-vpn", "allow"), ("zeta-cache", "allow"),
    ]
]  # fmt: skip
GOOD_ENTRY: dict[str, Any] = {
    "test_id": "test_rules_list_filter_next_page",
    "settings": {"capabilities": {"rules": True}},
    "policy": {"rules": _RULES},
    "total_count": 7,
    "page_2_names": ["{test_id:12}-gamma-ssh", "{test_id:12}-zeta-cache"],
}


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData, list[str]]:
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("cache"))}}
    )
    index, _, _ = update_index(STANDIN, settings)
    return settings, index, first_party(index, settings)


def _validate(
    setup: tuple[Settings, IndexData, list[str]],
    code: str = GOOD_CODE,
    entries: list[dict[str, Any]] | None = None,
    file_name: str = "tests/rules/test_rules_list_filter.py",
    ticket_id: str = "STND-106",
    data_text: str | None = "",
    draft: TestCaseDraft | None = None,
    settings: Settings | None = None,
    test_ids: list[str] | None = None,
) -> ValidationReport:
    base_settings, index, fp = setup
    settings = settings or base_settings
    entries = copy.deepcopy([GOOD_ENTRY] if entries is None else entries)
    try:
        ids = computed_test_ids(code) if test_ids is None else test_ids
    except ValueError:
        ids = []
    generated = GeneratedTest(
        code=code,
        file_name=file_name,
        data_file_name=file_name.replace(".py", ".json"),
        data_entries=entries,
        data_format="array",
        test_ids=ids,
        template_entry_ref=None,
        ticket_id=ticket_id,
        draft_ref=f"{ticket_id}/d1",
        retrieved_chunk_ids=[],
        prompt_version="test",
        provider="fake",
        model="fake",
        attempts=1,
        context_tokens=0,
    )
    if data_text == "":
        data_text = format_entries(entries, settings.data, settings.style.json_files, "array")
    imports = module_imports(index)
    return validate_generated(
        generated, index.catalog, settings, fp, draft, data_text, imports, index
    )


def _messages(report: ValidationReport, check: str, severity: str = "error") -> list[str]:
    return [f.message for f in report.findings if f.check == check and f.severity == severity]


def _replace(old: str, new: str, code: str = GOOD_CODE) -> str:
    assert old in code, old
    return code.replace(old, new)


# --- the reference passes ---------------------------------------------------------------------


def test_a_good_pair_has_no_findings(setup: Any) -> None:
    report = _validate(setup)
    assert report.ok and report.findings == [], [f.render() for f in report.findings]
    assert {"syntax", "names", "chains", "ids", "data_keys", "claims"} <= set(report.checks_run)


def test_the_hand_written_standin_suite_has_no_errors(setup: Any) -> None:
    from ticket2test.validate.suite import _function_file_entries, local_checks

    settings, index, _ = setup
    for path in sorted((STANDIN / "tests").rglob("test_*.py")):
        relative = path.relative_to(STANDIN).as_posix()
        if index.files[relative].info is None:
            continue  # v6: a Python 2 leftover, left out of the index (and of collection)
        if path.parent.name == "units":
            continue  # v7: the legacy area (generate.reuse.legacy_domains), never a template
        ids = [  # from the index: includes inherited tests
            t
            for c in index.chunks
            if c.kind == "test" and c.file_path == relative
            for t in c.test_ids
        ]
        code = path.read_text(encoding="utf-8")
        data_path = path.with_suffix(".json")
        data_text = data_path.read_text(encoding="utf-8") if data_path.exists() else None
        entries = json.loads(data_text) if data_text else []
        extra = _function_file_entries(STANDIN, relative, index, settings)
        if extra:  # tests with a data file of their own (v6)
            entries, data_text = [*entries, *extra], None
        report = _validate(
            setup,
            code=code,
            entries=entries,
            file_name=relative,
            ticket_id="NONE-0",
            data_text=data_text,
            test_ids=ids,
        )
        older = local_checks(settings)  # v7: rules older tests break (deviations)
        errors = [f.render() for f in report.errors if f.check not in older]
        assert not errors, (path.name, errors)


# --- code -------------------------------------------------------------------------------------


def test_syntax_error_stops_the_other_checks(setup: Any) -> None:
    report = _validate(setup, code="def test_x(:\n")
    assert report.checks_run == ["syntax"] and _messages(report, "syntax")


def test_unknown_modules_and_names_in_known_modules(setup: Any) -> None:
    code = _replace(
        "from framework.decorators import browsers, data_driven, environments",
        "from framework.decorators import browsers, data_driven, environments, flaky\n"
        "import requests",
    )
    messages = _messages(_validate(setup, code=code), "imports")
    assert any("has no name 'flaky'" in m for m in messages)
    assert any("unknown module 'requests'" in m for m in messages)


def test_undefined_plain_names(setup: Any) -> None:
    code = _replace("rules.next_page()", "rules.next_page()\n      wait_for(rules)")
    assert _messages(_validate(setup, code=code), "names") == ["undefined name 'wait_for'"]


def test_a_missing_property_chain_is_caught(setup: Any) -> None:
    code = _replace("rules.total_count)", "rules.rule_count)")
    messages = _messages(_validate(setup, code=code), "names")
    assert messages == ["rules (RuleListPage) has no member 'rule_count' (in rules.rule_count)"]
    code = _replace("rules = self.nav.rules.list", "rules = self.nav.rule.list")
    messages = _messages(_validate(setup, code=code), "names")
    assert messages and "Navigator) has no member 'rule'" in messages[0]


def test_page_object_usage_properties_actions_and_no_chaining(setup: Any) -> None:
    called_property = _replace("rules.total_count)", "rules.total_count())")
    uncalled_action = _replace("rules.search()", "rules.search")
    assigned_action = _replace('rules.action_filter = "allow"', 'rules.search = "allow"')
    chained = _replace(
        "rules = self.nav.rules.list\n      rules.open()",
        "rules = self.nav.rules.list\n      self.nav.rules.list.open().search()",
    )
    for code, expected in [
        (called_property, "total_count is a property"),
        (uncalled_action, "search is an action method: call it"),
        (assigned_action, "search is an action method; it can't be assigned"),
        (chained, "no chaining"),
    ]:
        messages = _messages(_validate(setup, code=code), "page_objects")
        assert any(expected in m for m in messages), (expected, messages)


def test_assertions_use_the_suite_object(setup: Any) -> None:
    bare = _replace("self.check.assertEqual(2, rules.page_number)", "assert rules.page_number == 2")
    assert any("bare assert" in m for m in _messages(_validate(setup, code=bare), "assertions"))
    unknown = _replace("assertEqual(2, rules.page_number)", "assertEquals(2, rules.page_number)")
    messages = _messages(_validate(setup, code=unknown), "assertions")
    assert any("assertEquals is not an allowed assertion" in m for m in messages)
    start = GOOD_CODE.index("      self.check.assertEqual(self.params")
    no_checks = GOOD_CODE[:start].rstrip() + "\n"
    messages = _messages(_validate(setup, code=no_checks, entries=[]), "assertions")
    assert any("checks nothing" in m for m in messages)


def test_base_class_is_required(setup: Any) -> None:
    code = _replace("class TestRulesListFilter(BaseTest):", "class TestRulesListFilter:")
    code = _replace(
        "from framework.base_test import BaseTest\n", "", code
    )  # unused import gone too
    messages = _messages(_validate(setup, code=code), "base_class")
    # Discovered from the suite: the classes existing test classes directly inherit.
    expected = (
        "one of BaseTest, DownloadChecks, ExceptionsCommon, LegacyBrowserBase, ExceptionsTests"
    )
    assert messages == [f"class TestRulesListFilter must inherit {expected}"]


def test_base_classes_are_discovered_or_configured(setup: Any) -> None:
    from ticket2test.validate.validator import suite_base_classes

    settings, index, _ = setup
    assert suite_base_classes(index.catalog, settings) == [
        "BaseTest", "DownloadChecks", "ExceptionsCommon", "LegacyBrowserBase", "ExceptionsTests",
    ]  # fmt: skip
    listed = settings.model_copy(
        update={"validation": settings.validation.model_copy(update={"base_classes": ["X"]})}
    )
    assert suite_base_classes(index.catalog, listed) == ["X"]


def test_a_setup_hook_the_base_doesnt_use_is_flagged(setup: Any) -> None:
    """Real suites mix setup, setup_method and setUp; overriding a name the base classes
    don't use does nothing (or skips the base's setup)."""
    code = _replace("   def setup(self):", "   def setUp(self):")
    warnings = _messages(_validate(setup, code=code), "hooks", "warning")
    assert len(warnings) == 1 and "runs only in a unittest.TestCase class" in warnings[0]
    assert "define setup instead" in warnings[0]  # what BaseTest calls
    assert _messages(_validate(setup), "hooks", "warning") == []  # setup is what BaseTest uses


def test_any_of_several_base_classes_is_accepted(setup: Any) -> None:
    settings = setup[0].model_copy(deep=True)
    settings.validation.base_classes = ["BrowsingBase", "BaseTest"]  # one absent from the repo
    assert _messages(_validate(setup, settings=settings), "base_class") == []
    code = _replace("class TestRulesListFilter(BaseTest):", "class TestRulesListFilter:")
    code = _replace("from framework.base_test import BaseTest\n", "", code)
    assert _messages(_validate(setup, code=code, settings=settings), "base_class") == [
        "class TestRulesListFilter must inherit one of BrowsingBase, BaseTest"
    ]
    settings.validation.base_classes = ["BrowsingBase"]
    messages = _messages(_validate(setup, settings=settings), "base_class")
    assert messages and "none of the base classes" in messages[0]


def test_required_markers_and_approved_values(setup: Any) -> None:
    missing = _replace('   @pytest.mark.suite("regression")\n', "")
    assert _messages(_validate(setup, code=missing), "markers") == [
        "missing @pytest.mark.suite(...)"
    ]
    wrong_case = _replace('priority("p2")', 'priority("P2")')
    messages = _messages(_validate(setup, code=wrong_case), "markers")
    assert messages and "priority value 'P2' is not approved" in messages[0]
    unknown_component = _replace('component("rules")', 'component("firewall")')
    messages = _messages(_validate(setup, code=unknown_component), "markers")
    assert messages and "component value 'firewall'" in messages[0]


def test_naming_and_no_ticket_numbers(setup: Any) -> None:
    code = _replace("test_rules_list_filter_next_page", "test_rules_106_filter")
    entry = {**GOOD_ENTRY, "test_id": "test_rules_106_filter"}
    messages = _messages(_validate(setup, code=code, entries=[entry]), "naming")
    assert any("ticket id STND-106" in m for m in messages)
    camel = _replace("class TestRulesListFilter", "class Test_rules_list")
    messages = _messages(_validate(setup, code=camel), "naming")
    assert any("class name 'Test_rules_list'" in m for m in messages)
    module = _validate(setup, file_name="tests/rules/RulesFilter.py")
    assert any("module name 'RulesFilter'" in m for m in _messages(module, "naming"))


def test_style_rules(setup: Any) -> None:
    annotated = _replace("def setup(self):", "def setup(self) -> None:")
    assert any("annotations" in m for m in _messages(_validate(setup, code=annotated), "style"))
    four_spaces = GOOD_CODE.replace("   ", "    ")
    fixed = setup[0].model_copy(
        update={"style": setup[0].style.model_copy(update={"follow_local": False})}
    )
    messages = _messages(_validate(setup, code=four_spaces, settings=fixed), "style")
    assert any("not formatted" in m for m in messages)
    # Following the local style, a consistent file in another indent is fine; a messy one isn't.
    assert not _messages(_validate(setup, code=four_spaces), "style")
    messy = GOOD_CODE.replace("rules.search()", "rules.search( )")
    assert any("not formatted" in m for m in _messages(_validate(setup, code=messy), "style"))
    crlf = GOOD_CODE.replace("\n", "\r\n")
    assert any("LF" in m for m in _messages(_validate(setup, code=crlf), "style"))


# --- data -------------------------------------------------------------------------------------

STACKED = """import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("rules")
class TestRulesListFilter(BaseTest):
   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("action", ["allow", "deny"])
   @pytest.mark.parametrize("page", [1, 2])
   def test_rules_list_filter_paged(self, action, page):
      rules = self.nav.rules.list
      rules.open()
      rules.action_filter = action
      rules.search()
      self.check.assertEqual(self.params["total_count"], rules.total_count)
"""


def test_entries_keyed_in_the_wrong_stacked_order_are_caught(setup: Any) -> None:
    right = [
        {"test_id": f"test_rules_list_filter_paged[{p}-{a}]", "total_count": 1}
        for a in ("allow", "deny")
        for p in (1, 2)
    ]
    assert _messages(_validate(setup, code=STACKED, entries=right), "ids") == []
    wrong = [
        {"test_id": f"test_rules_list_filter_paged[{a}-{p}]", "total_count": 1}
        for a in ("allow", "deny")
        for p in (1, 2)
    ]  # top decorator first: the wrong order
    messages = _messages(_validate(setup, code=STACKED, entries=wrong), "ids")
    assert any("entries for ids the code doesn't produce" in m for m in messages)
    missing = [f for f in _validate(setup, code=STACKED, entries=wrong).errors if f.test]
    assert {f.test for f in missing} == {
        "test_rules_list_filter_paged[1-allow]",
        "test_rules_list_filter_paged[2-allow]",
        "test_rules_list_filter_paged[1-deny]",
        "test_rules_list_filter_paged[2-deny]",
    }


def test_data_keys_read_must_exist_and_every_key_must_be_used(setup: Any) -> None:
    lacking = {k: v for k, v in GOOD_ENTRY.items() if k != "page_2_names"}
    messages = _messages(_validate(setup, entries=[lacking]), "data_keys")
    assert messages == ["reads keys its entry lacks: ['page_2_names']"]
    unread = {**GOOD_ENTRY, "last_page_count": 2}
    messages = _messages(_validate(setup, entries=[unread]), "data_keys")
    assert messages and "custom key 'last_page_count' is never read" in messages[0]
    unread_target = {**GOOD_ENTRY, "targets": []}
    messages = _messages(_validate(setup, entries=[unread_target]), "data_keys")
    assert messages and "only read by self.verify_targets()" in messages[0]
    both = {**GOOD_ENTRY, "targets": [], "interactions": []}  # neither helper is called
    messages = _messages(_validate(setup, entries=[both]), "data_keys")
    assert messages and "verify_targets()" in messages[0] and "verify_interactions()" in messages[0]


def test_data_file_formatting(setup: Any) -> None:
    text = json.dumps([GOOD_ENTRY], indent=2)
    fixed = setup[0].model_copy(
        update={"style": setup[0].style.model_copy(update={"follow_local": False})}
    )
    messages = _messages(_validate(setup, data_text=text, settings=fixed), "data_file")
    assert messages == ["the data file is not formatted to the suite's JSON style"]
    assert not _messages(_validate(setup, data_text=text), "data_file")  # its own style
    mixed = text.replace('"policy": {', '"policy":{', 1)
    messages = _messages(_validate(setup, data_text=mixed), "data_file")
    assert messages == ["the data file is not formatted to the suite's JSON style"]


def test_seeded_names_use_the_placeholder_and_fit_the_cap(setup: Any) -> None:
    literal = copy.deepcopy(GOOD_ENTRY)
    literal["policy"]["rules"][0]["name"] = "web-access"
    messages = _messages(_validate(setup, entries=[literal]), "names_unique")
    assert messages and "'web-access' is a literal" in messages[0]
    long = copy.deepcopy(GOOD_ENTRY)
    long["policy"]["rules"][0]["name"] = "{test_id:24}-alpha-web"
    messages = _messages(_validate(setup, entries=[long]), "name_length")
    assert messages == ["'{test_id:24}-alpha-web' can be 34 characters; the limit is 32"]
    typed = _replace('rules.action_filter = "allow"', 'rules.search_text = "x"')
    typed = typed.replace("rules.search()", "rules.search()\n      self.unique_name(40)")
    messages = _messages(_validate(setup, code=typed), "name_length")
    assert messages == ["self.unique_name(40) exceeds the name limit 32"]


def test_typed_literal_names_are_caught(setup: Any) -> None:
    code = _replace(
        "rules.next_page()",
        'rules.add_rule()\n      wizard = self.nav.rules.wizard\n      wizard.name = "web-access"',
    )
    messages = _messages(_validate(setup, code=code), "names_unique")
    assert messages and "typed name 'web-access' is a literal" in messages[0]


# --- heuristics (warnings) ---------------------------------------------------------------------


def test_unused_capability_gates_are_a_warning(setup: Any) -> None:
    entry = copy.deepcopy(GOOD_ENTRY)
    entry["settings"]["capabilities"] = {"rules": True, "profiles": True}
    report = _validate(setup, entries=[entry])
    assert report.ok
    assert _messages(report, "capabilities", "warning") == [
        "seeds capability gates 'rules' features don't use: ['profiles']"
    ]


V3_CHECKS = """      rules.next_page()

      self.check.assertEqual(2, rules.page_number)
      self.check.assertEqual("allow", rules.action_filter)
      self.check.assertEqual(self.params["total_count"], rules.total_count)
      self.check.assertEqual(self.params["last_page_count"], len(rules.rule_names))
"""


def _v3_code() -> str:
    """The third style check's STND-106 shape: page 2 is checked only by counts."""
    start = GOOD_CODE.index('      self.check.assertEqual(self.params["total_count"]')
    head = GOOD_CODE[:start].replace("      2. Page 1 is full and shows only allow rules.\n", "")
    head = head.replace("3. Go to", "2. Go to").replace("4. Page 2", "3. Page 2")
    return head + V3_CHECKS


def test_claims_checked_only_by_counts_are_flagged(setup: Any) -> None:
    entry = {**GOOD_ENTRY, "last_page_count": 2}
    del entry["page_2_names"]
    report = _validate(setup, code=_v3_code(), entries=[entry])
    assert report.ok
    assert _messages(report, "claims", "warning") == [
        "docstring claims 'Page 2 shows only allow rules': checked only by a count or a "
        "single value"
    ]
    assert any("never reads page_size" in m for m in _messages(report, "constants", "warning"))


def test_claims_nobody_checks_are_flagged(setup: Any) -> None:
    code = _replace(
        "4. Page 2 shows only allow rules and the allow filter stays selected.",
        "4. Page 2 shows only allow rules and the export button is hidden.",
    )
    messages = _messages(_validate(setup, code=code), "claims", "warning")
    assert messages == ["docstring claims 'the export button is hidden': not checked"]


def test_the_drafts_expected_outcome_is_a_claim(setup: Any) -> None:
    draft = TestCaseDraft.model_validate(
        {
            "id": "STND-106/d1",
            "ticket_id": "STND-106",
            "kind": "primary",
            "intent": "Filter kept on the next page",
            "markers": {"priority": "p2", "component": "rules", "suite": "regression"},
            "test_kind": "ui",
            "deployment_type": "both",
            "preconditions": [],
            "steps": ["Filter by allow", "Next page"],
            "expected_outcome": "An audit entry is written",
            "variants": [],
            "prompt_version": "draft_v1",
        }
    )
    messages = _messages(_validate(setup, draft=draft), "claims", "warning")
    assert messages == ["expected outcome claims 'An audit entry is written': not checked"]


def test_every_draft_variant_has_a_case(setup: Any) -> None:
    def variant(name: str, value: str) -> dict[str, Any]:
        return {"name": name, "inputs": [{"name": "action", "value": value}], "expected": "x"}

    draft = TestCaseDraft.model_validate(
        {
            "id": "STND-106/d1",
            "ticket_id": "STND-106",
            "kind": "primary",
            "intent": "Filter kept on the next page",
            "markers": {"priority": "p2", "component": "rules", "suite": "regression"},
            "test_kind": "ui",
            "deployment_type": "both",
            "preconditions": [],
            "steps": ["Filter by the action", "Next page"],
            "expected_outcome": "Only rules with that action are shown",
            "variants": [
                variant("allow rules", "Allow"),
                variant("quarantine rules", "quarantine"),
            ],
            "prompt_version": "draft_v1",
        }
    )
    messages = _messages(_validate(setup, draft=draft), "variants")
    assert len(messages) == 1  # "allow" is in the code; "quarantine" is nowhere
    assert messages[0].startswith("the draft's variant 'quarantine rules' (action='quarantine')")


# --- CLI ----------------------------------------------------------------------------------------


def _write_generated(folder: Path, code: str = GOOD_CODE) -> Path:
    from ticket2test.config import Settings as _S

    settings = _S()
    generated = GeneratedTest(
        code=code,
        file_name="tests/rules/test_rules_list_filter.py",
        data_file_name="tests/rules/test_rules_list_filter.json",
        data_entries=[GOOD_ENTRY],
        data_format="array",
        test_ids=computed_test_ids(code),
        template_entry_ref=None,
        ticket_id="STND-106",
        draft_ref="STND-106/d1",
        retrieved_chunk_ids=[],
        prompt_version="test",
        provider="fake",
        model="fake",
        attempts=1,
        context_tokens=0,
    )
    target = folder / "STND-106_d1"
    (target / "tests/rules").mkdir(parents=True)
    (target / generated.file_name).write_text(code, encoding="utf-8")
    (target / generated.data_file_name).write_text(
        format_entries([GOOD_ENTRY], settings.data, settings.style.json_files, "array"),
        encoding="utf-8",
    )
    path = target / "generated.json"
    path.write_text(generated.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_cli_validate_writes_the_report_and_sets_the_exit_code(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from ticket2test.cli import app

    runner = CliRunner()
    good = _write_generated(tmp_path / "good")
    result = runner.invoke(app, ["validate", str(tmp_path / "good"), "--repo", str(STANDIN)])
    assert result.exit_code == 0, result.output
    assert "1/1 passed" in result.output
    stored = GeneratedTest.model_validate_json(good.read_text(encoding="utf-8"))
    assert stored.validation_report is not None and stored.validation_report["findings"] == []

    _write_generated(tmp_path / "bad", GOOD_CODE.replace("rules.total_count)", "rules.rule_count)"))
    result = runner.invoke(app, ["validate", str(tmp_path / "bad"), "--repo", str(STANDIN)])
    assert result.exit_code == 1 and "no member 'rule_count'" in result.output

    result = runner.invoke(
        app, ["validate", str(tmp_path / "good"), "--repo", str(STANDIN), "--run"]
    )
    assert result.exit_code == 2 and "not available yet" in result.output


def test_cli_collect_without_a_runtime_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from typer.testing import CliRunner

    from ticket2test.cli import app

    monkeypatch.setattr(shutil, "which", lambda name: None)
    _write_generated(tmp_path / "good")
    runner = CliRunner()
    args = ["validate", str(tmp_path / "good"), "--repo", str(STANDIN), "--collect"]
    result = runner.invoke(app, args)
    assert result.exit_code == 2 and "never collected on the host" in result.output
    result = runner.invoke(app, ["sandbox"])
    assert result.exit_code == 2 and "not found" in result.output


def test_claim_clauses_keep_lists_quotes_and_negations_together() -> None:
    from ticket2test.validate.claims import clauses

    assert clauses("All rules (alpha-web, alpha-mail) are listed, whatever their case.") == [
        "All rules (alpha-web, alpha-mail) are listed",
        "whatever their case",
    ]
    assert clauses("The rule has the action deny, not allow.") == [
        "The rule has the action deny, not allow"
    ]
    assert clauses('The toast says "Saved, published" and the list is empty') == [
        'The toast says "Saved, published"',
        "the list is empty",
    ]
    assert clauses("The tenant's policy has the rule; the primary's is unchanged") == [
        "The tenant's policy has the rule",
        "the primary's is unchanged",
    ]


def test_names_a_package_re_exports_are_known(setup: Any) -> None:
    from ticket2test.validate.validator import module_imports

    _, index, _ = setup
    code = _replace(
        "from framework.decorators import browsers, data_driven, environments",
        "from framework.decorators import browsers, data_driven, environments\n"
        "from framework.pages import Navigator",
    )
    code = code.replace("rules.next_page()", "rules.next_page()\n      Navigator")
    settings, _, fp = setup
    generated = GeneratedTest.model_validate(
        {
            "code": code,
            "file_name": "tests/rules/test_rules_list_filter.py",
            "data_file_name": "tests/rules/test_rules_list_filter.json",
            "data_entries": [GOOD_ENTRY],
            "data_format": "array",
            "test_ids": computed_test_ids(code),
            "template_entry_ref": None,
            "ticket_id": "STND-106",
            "draft_ref": "d",
            "retrieved_chunk_ids": [],
            "prompt_version": "t",
            "provider": "f",
            "model": "f",
            "attempts": 1,
            "context_tokens": 0,
        }
    )
    without = validate_generated(generated, index.catalog, settings, fp)
    assert _messages(without, "imports") == ["framework.pages has no name 'Navigator'"]
    report = validate_generated(
        generated, index.catalog, settings, fp, imports=module_imports(index)
    )
    assert not [f for f in report.findings if f.check == "imports"]


def test_placeholder_syntax_comes_from_config(setup: Any) -> None:
    base_settings, _, _ = setup
    settings = base_settings.model_copy(
        update={
            "validation": base_settings.validation.model_copy(
                update={
                    "placeholder_pattern": r"\$\{[a-z]+(?::\d+)?\}",
                    "unique_name_pattern": r"\$\{unique:(\d+)\}",
                }
            )
        }
    )
    entry = copy.deepcopy(GOOD_ENTRY)
    for rule in entry["policy"]["rules"]:
        rule["name"] = rule["name"].replace("{test_id:12}", "${unique:12}")
    entry["page_2_names"] = [
        n.replace("{test_id:12}", "${unique:12}") for n in entry["page_2_names"]
    ]
    report = _validate(setup, entries=[entry], settings=settings)
    assert not [f for f in report.findings if f.check in ("names_unique", "name_length")]
    entry["policy"]["rules"][0]["name"] = "${unique:30}-alpha-web"
    report = _validate(setup, entries=[entry], settings=settings)
    assert _messages(report, "name_length") == [
        "'${unique:30}-alpha-web' can be 40 characters; the limit is 32"
    ]
    # With the default (stand-in) patterns, the length check can't see the new syntax.
    assert not _messages(_validate(setup, entries=[entry]), "name_length")


# --- reuse: inherited tests and tests calling tests ----------------------------------------------

REUSE_CODE = """import pytest

from framework.decorators import browsers, data_driven, environments
from tests.files.checks import DownloadChecks


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("files")
class TestFilesReports(DownloadChecks):
   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_files_reports_view_after_download(self):
      self.test_files_download_verdict()
      self.nav.files.view_file(self.params["file"])
      self.check.assertEqual("read-only", self.nav.files.viewer.mode)
"""
REUSE_ENTRIES: list[dict[str, Any]] = [
    {
        "test_id": test_id,
        "site": {"files": [{"name": "report.pdf", "content": "x"}]},
        "file": "report.pdf",
        "decision": "converted",
        "targets": [{"method": "GET", "path": "/api/downloads/v1/log/:tid", "response": []}],
    }
    for test_id in ("test_files_download_verdict", "test_files_reports_view_after_download")
]


def test_a_class_reusing_a_base_gets_its_inherited_tests_and_helpers(setup: Any) -> None:
    file_name = "tests/files/test_files_reports.py"
    report = _validate(
        setup,
        code=REUSE_CODE,
        entries=REUSE_ENTRIES,
        file_name=file_name,
        test_ids=["test_files_reports_view_after_download", "test_files_download_verdict"],
    )
    # The inherited test's entry is not an orphan; the called test's keys and its
    # verify_targets() count as used; the base's helper resolves through DownloadChecks.
    assert report.ok, [f.render() for f in report.errors]


def test_keys_a_called_test_reads_must_exist(setup: Any) -> None:
    entries = copy.deepcopy(REUSE_ENTRIES)
    del entries[1]["decision"]  # read by test_files_download_verdict, which the test calls
    report = _validate(
        setup,
        code=REUSE_CODE,
        entries=entries,
        file_name="tests/files/test_files_reports.py",
        test_ids=["test_files_reports_view_after_download", "test_files_download_verdict"],
    )
    assert _messages(report, "data_keys") == ["reads keys its entry lacks: ['decision']"]
    missing_inherited = _validate(
        setup,
        code=REUSE_CODE,
        entries=REUSE_ENTRIES[1:],
        file_name="tests/files/test_files_reports.py",
        test_ids=["test_files_reports_view_after_download", "test_files_download_verdict"],
    )
    assert [f.test for f in missing_inherited.errors if f.check == "ids"] == [
        "test_files_download_verdict"
    ]


def test_seed_data_has_the_shape_the_suite_uses(setup: Any) -> None:
    """A real-case run: page data written as an object keyed by path loaded fine but broke
    the seed at run time; the suite always writes a list of pages."""
    as_object = {**GOOD_ENTRY, "site": {"pages": {"/pages/x": {"text": "hello"}}}}
    messages = _messages(_validate(setup, entries=[as_object]), "data_shape")
    assert messages == [
        "site.pages is an object here, but a list in every data file of the suite: "
        "write it the way the existing entries do"
    ]
    as_list = {**GOOD_ENTRY, "site": {"pages": [{"path": "/pages/x", "text": "hello"}]}}
    assert _messages(_validate(setup, entries=[as_list]), "data_shape") == []


def test_testcase_classes_may_assert_on_self(setup: Any) -> None:
    """Real suites mix a separate assertion object with self.assert* in classes that inherit
    unittest.TestCase."""
    code = _replace("import pytest\n", "import unittest\n\nimport pytest\n")
    code = _replace(
        "class TestRulesListFilter(BaseTest):",
        "class TestRulesListFilter(BaseTest, unittest.TestCase):",
        code,
    )
    code = code.replace("self.check.assertEqual(", "self.assertEqual(")
    report = _validate(setup, code=code)
    assert _messages(report, "assertions") == []
    # Without TestCase in the lineage, self.assertEqual isn't the suite's assertion style.
    plain = GOOD_CODE.replace("self.check.assertEqual(", "self.assertEqual(")
    assert any("checks nothing" in m for m in _messages(_validate(setup, code=plain), "assertions"))


def test_only_assert_methods_on_self_count() -> None:
    from ticket2test.validate.code import is_assertion

    assert is_assertion("self.assertIn", "self.check", True)
    assert is_assertion("self.fail", "self.check", True)
    assert not is_assertion("self.unique_name", "self.check", True)  # a helper, not a check
    assert not is_assertion("self.assertIn", "self.check", False)
    assert is_assertion("self.check.whatever", "self.check", False)  # judged by the method list


def test_joined_marker_values_are_checked_part_by_part(setup: Any) -> None:
    joined = _replace('@pytest.mark.component("rules")', '@pytest.mark.component("rules,profiles")')
    assert _messages(_validate(setup, code=joined), "markers") == []  # both parts known
    unknown = _replace('@pytest.mark.component("rules")', '@pytest.mark.component("rules,nope")')
    messages = _messages(_validate(setup, code=unknown), "markers")
    assert len(messages) == 1 and "component value 'nope' is not approved" in messages[0]
    assert GOOD_CODE.count('@pytest.mark.component("rules")') == 1


def test_tests_never_use_page_locators(setup: Any) -> None:
    """Dev-set finding: a test clicked a page object's locator constant because the page had
    no action for the button; nothing was invented, so the missing action went unseen."""
    code = _replace("      rules.search()\n", "      rules.click(rules.SEARCH_BUTTON)\n")
    messages = _messages(_validate(setup, code=code), "page_locators")
    assert len(messages) == 1 and "rules.SEARCH_BUTTON is a page object's locator" in messages[0]
    assert "call it by the name it would have" in messages[0]
    assert _messages(_validate(setup), "page_locators") == []


def test_tests_never_use_the_raw_driver(setup: Any) -> None:
    """Held-out v6 finding: with no page action for a link, a test opened the URL with the raw
    driver; the gap was reported, but the test went around the page objects."""
    code = _replace(
        "      rules.search()\n",
        '      self.driver.get(self.config.base_url + "/rules?q=alpha")\n',
    )
    messages = _messages(_validate(setup, code=code), "raw_driver")
    assert len(messages) == 1 and "uses the browser driver directly" in messages[0]
    assert _messages(_validate(setup), "raw_driver") == []


def test_syntax_newer_than_the_suites_python_is_an_error(setup: Any) -> None:
    settings = setup[0]
    py38 = settings.model_copy(
        update={
            "style": settings.style.model_copy(
                update={
                    "python": settings.style.python.model_copy(update={"target_version": "3.8"})
                }
            )
        }
    )
    code = GOOD_CODE.replace(
        "      rules.search()\n",
        "      rules.search()\n      match 1:\n         case 1:\n            pass\n",
        1,
    )
    assert code != GOOD_CODE
    assert any(
        "newer than the suite's Python 3.8" in m
        for m in _messages(_validate(setup, code=code, settings=py38), "syntax")
    )
    assert not _messages(_validate(setup, code=code), "syntax")  # no target: this tool's Python
    assert not _messages(_validate(setup, settings=py38), "syntax")


def test_markers_from_module_class_body_and_constants_count(setup: Any) -> None:
    """Found on the first real-suite check-suite: markers set with ``pytestmark`` (module or
    class body) or with a non-literal value were reported missing on correct tests."""
    no_method_marks = GOOD_CODE.replace('   @pytest.mark.priority("p2")\n', "", 1).replace(
        '   @pytest.mark.suite("regression")\n', "", 1
    )
    assert any(
        "missing @pytest.mark.priority" in m
        for m in _messages(_validate(setup, code=no_method_marks), "markers")
    )
    module = no_method_marks.replace(
        "\n\n@browsers", '\n\npytestmark = [pytest.mark.priority("p2")]\n\n\n@browsers', 1
    ).replace(
        "class TestRulesListFilter(BaseTest):\n",
        "class TestRulesListFilter(BaseTest):\n   pytestmark = pytest.mark.suite(SUITE)\n",
        1,
    )
    assert not _messages(_validate(setup, code=module), "markers")


def test_markers_on_a_base_class_count_for_its_subclasses(tmp_path: Path) -> None:
    from ticket2test.generate.generator import first_party

    repo = tmp_path / "repo"
    (repo / "framework").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "framework" / "base.py").write_text(
        'import pytest\n\n\n@pytest.mark.project("example-project")\nclass AreaBase:\n'
        '   pytestmark = [pytest.mark.suite("regression")]\n',
        encoding="utf-8",
    )
    code = (
        "import pytest\n\nfrom framework.base import AreaBase\n\n\n"
        '@pytest.mark.component("rules")\nclass TestArea(AreaBase):\n'
        '   @pytest.mark.priority("p2")\n   def test_area_one(self):\n      pass\n'
    )
    (repo / "tests" / "test_area.py").write_text(code, encoding="utf-8")
    settings = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}})
    index, _, _ = update_index(repo, settings)
    report = _validate(
        (settings, index, first_party(index, settings)),
        code=code,
        entries=[],
        file_name="tests/test_area.py",
        test_ids=["test_area_one"],
    )
    assert not _messages(report, "markers"), _messages(report, "markers")


def test_the_suites_own_check_helpers_count_as_checks() -> None:
    """A real suite checks through its own helpers (``verify_*``, log waits): with
    ``validation.check_helpers`` those calls count, so such a test isn't "checking nothing"."""
    import ast

    from ticket2test.validate.code import check_calls

    fn = ast.parse("def test_x(self):\n    self.page.verify_shown()\n").body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert not check_calls(fn, "self.check", set())
    assert check_calls(fn, "self.check", set(), check_helpers=["verify_*"])
    assert not check_calls(fn, "self.check", set(), check_helpers=["wait_for_*"])


def test_self_members_come_from_every_base_class(tmp_path: Path) -> None:
    """Found in a real trial: ``class T(LogMixin, AreaBase)`` had its ``AreaBase`` members
    reported missing, because only the first base was looked at."""
    from ticket2test.generate.generator import first_party

    repo = tmp_path / "repo"
    (repo / "framework").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "framework" / "base.py").write_text(
        "class LogMixin:\n   def read_log(self):\n      return []\n\n\n"
        "class AreaBase:\n   def open_home(self):\n      pass\n",
        encoding="utf-8",
    )
    code = (
        "from framework.base import AreaBase, LogMixin\n\n\n"
        "class TestArea(LogMixin, AreaBase):\n   def test_area_one(self):\n"
        "      self.open_home()\n      self.read_log()\n      self.not_there()\n"
    )
    (repo / "tests" / "test_area.py").write_text(code, encoding="utf-8")
    settings = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}})
    index, _, _ = update_index(repo, settings)
    report = _validate(
        (settings, index, first_party(index, settings)),
        code=code,
        entries=[],
        file_name="tests/test_area.py",
        test_ids=["test_area_one"],
    )
    missing = [m for m in _messages(report, "names") if "has no member" in m]
    assert len(missing) == 1 and "'not_there'" in missing[0], missing


def test_data_handed_to_a_check_through_a_local_counts_for_the_claims() -> None:
    """Found in a real trial: ``row = params["targets"][0]`` then ``self._verify_log(row)``
    checks the row's values, though no key is written in the call."""
    import ast

    from ticket2test.validate.claims import data_locals, find_gaps
    from ticket2test.validate.code import check_calls

    fn = ast.parse(
        "def test_x(self, params):\n"
        '    row = params["targets"][0]\n'
        '    first = row.get("event")\n'
        "    self._verify_log(row)\n"
    ).body[0]
    assert isinstance(fn, ast.FunctionDef)
    locals_ = data_locals(fn, ["self.params", "params"])
    assert locals_ == {"row": "targets", "first": "targets"}
    checks = check_calls(fn, "self.check", set(), check_helpers=["_verify_*"])
    entries = [{"test_id": "test_x", "targets": [{"event": "verdict", "malicious": "true"}]}]
    claim = [("expected outcome", "The verdict event is logged")]
    assert find_gaps(claim, checks, entries, {})  # the call names no data key
    assert not find_gaps(claim, checks, entries, {}, data=locals_)
