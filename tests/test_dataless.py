"""A test for a class that keeps no data (no data file in its area): generation takes a test
without an entry as its template, the new test reads no data, and no data file is written.

Found on the real suite: a whole area without data files made every golden run of its ticket
fail ("no template test with a JSON data entry"). The stand-in's ``TestExceptionsWidgets`` is
such a class."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import Settings
from ticket2test.generate.context import DATALESS_NOTE
from ticket2test.generate.generator import GenerationError, generate_test
from ticket2test.generate.patch import method_patch, method_retrieval, validate_patch
from ticket2test.generate.reuse import ReuseDecision
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm import FakeLLMClient
from ticket2test.models import TestCaseDraft
from ticket2test.models.retrieval import RetrievalResult, TemplateRef
from ticket2test.validate.validator import validate_generated

STANDIN = REPO_ROOT / "standin"
WIDGETS = "tests/exceptions/test_exceptions_widgets.py"
CLASS = "TestExceptionsWidgets"

CODE = '''"""The exceptions list shows its title."""

import pytest

from framework.decorators import browsers, environments
from tests.exceptions.exceptions_common import ExceptionsCommon


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@pytest.mark.project("example-project")
@pytest.mark.component("exceptions")
class TestExceptionsWidgetsTitle(ExceptionsCommon):
   def setup(self):
      self.base_setup(fresh_driver=False, policy_wait=False)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_title_shown(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Exceptions", exceptions.page_title)
'''
READS_DATA = CODE.replace('"Exceptions", exceptions', 'self.params["title"], exceptions')


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("cache"))}}
    )
    index, _, _ = update_index(STANDIN, settings)
    return settings, index


def _draft() -> TestCaseDraft:
    return TestCaseDraft.model_validate(
        {
            "id": "STND-999/d1",
            "ticket_id": "STND-999",
            "kind": "primary",
            "intent": "The exceptions list shows its title",
            "markers": {"priority": "p3", "component": "exceptions", "suite": "regression"},
            "test_kind": "ui",
            "deployment_type": "both",
            "preconditions": [],
            "steps": ["Open the exceptions list"],
            "expected_outcome": "The page title is Exceptions.",
            "variants": [],
            "prompt_version": "x",
        }
    )


def _retrieval(index: IndexData) -> RetrievalResult:
    """No template with a data entry, as in an area without data files: the widgets class is
    put first the way the method path does it."""
    empty = RetrievalResult(ticket_id="X", repo_root=".", query_text="", hits=[], templates=[])
    return method_retrieval(empty, index, CLASS, WIDGETS)


def _reply(code: str, entries: list[dict[str, Any]] | None = None) -> str:
    return json.dumps(
        {
            "module_name": "test_exceptions_widgets_title",
            "code": code,
            "entries": entries or [],
            "review_checklist": [],
            "notes": "ok",
        }
    )


def _generate(setup: tuple[Settings, IndexData], fake: FakeLLMClient):  # type: ignore[no-untyped-def]
    settings, index = setup
    return generate_test(
        _draft(), _retrieval(index), index, settings, fake, provider="fake", model="fake-model"
    )


def test_a_class_without_data_gives_a_template_without_an_entry(
    setup: tuple[Settings, IndexData],
) -> None:
    _settings, index = setup
    templates = _retrieval(index).templates
    assert len(templates) == 1 and templates[0].entry_key is None
    assert templates[0].chunk_id.startswith(f"{WIDGETS}::{CLASS}.")


def test_a_test_without_data_is_generated_without_a_data_file(
    setup: tuple[Settings, IndexData],
) -> None:
    settings, index = setup
    fake = FakeLLMClient([_reply(CODE)])
    generated = _generate(setup, fake)
    prompt = fake.requests[0].messages[-1].content
    assert DATALESS_NOTE in prompt and "Base entry" not in prompt
    assert generated.data_file_name == "" and generated.data_entries == []
    assert generated.template_entry_ref is None
    assert any(c.startswith("No data template") for c in generated.review_checklist)
    report = validate_generated(generated, index.catalog, settings, index=index)
    data_checks = {"ids", "data_keys", "data_file", "data_shape"}
    assert [f.render() for f in report.errors if f.check in data_checks] == []


def test_a_test_that_reads_data_anyway_goes_back_with_the_reason(
    setup: tuple[Settings, IndexData],
) -> None:
    entry = {"test_id": "test_exceptions_widget_title_shown", "copy_sections": [], "changes": []}
    fake = FakeLLMClient([_reply(READS_DATA), _reply(CODE, [entry]), _reply(CODE)])
    generated = _generate(setup, fake)
    assert generated.attempts == 3
    assert "keeps no data entries" in fake.requests[1].messages[-1].content
    assert "test_exceptions_widget_title_shown" in fake.requests[1].messages[-1].content
    assert generated.data_entries == []


def test_a_method_for_a_class_without_data_patches_only_the_code(
    setup: tuple[Settings, IndexData],
) -> None:
    settings, index = setup
    generated = _generate(setup, FakeLLMClient([_reply(CODE)]))
    decision = ReuseDecision(
        kind="method",
        domain="exceptions",
        domain_uncertain=False,
        target=CLASS,
        target_file=WIDGETS,
        reasons=["test decision"],
    )
    patched = method_patch(generated, decision, index, settings, STANDIN)
    assert [p.path for p in patched.patches] == [WIDGETS]  # no data file created
    assert patched.data_file_name == "" and patched.new_test_ids == [
        "test_exceptions_widget_title_shown"
    ]
    report = validate_patch(patched, index, settings, STANDIN)
    assert report.errors == [], [f.render() for f in report.errors]


def test_without_any_test_to_copy_generation_still_fails_cleanly(
    setup: tuple[Settings, IndexData], tmp_path: Path
) -> None:
    settings, index = setup
    empty = RetrievalResult(ticket_id="X", repo_root=".", query_text="", hits=[], templates=[])
    with pytest.raises(GenerationError, match="no template test"):
        generate_test(_draft(), empty, index, settings, FakeLLMClient([]), provider="f", model="m")
    ref = TemplateRef(chunk_id="missing::Nothing.test_x", entry_key=None, why="gone")
    with pytest.raises(GenerationError, match="no template test"):
        generate_test(
            _draft(),
            empty.model_copy(update={"templates": [ref]}),
            index,
            settings,
            FakeLLMClient([]),
            provider="f",
            model="m",
        )
    _ = tmp_path
