"""Reuse patches: new cases of a parametrized test, new methods in a class, patch validation."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import Settings
from ticket2test.generate.patch import (
    CODE_PLAN,
    PatchError,
    method_patch,
    method_retrieval,
    parametrize_site,
    plan_variants_in_code,
    splice_methods,
    validate_patch,
    variant_patch,
)
from ticket2test.generate.reuse import ReuseDecision
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm.fake import FakeLLMClient
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import GeneratedTest
from ticket2test.models.retrieval import RetrievalResult, TemplateRef

STANDIN = REPO_ROOT / "standin"
TYPE_ACTION = (
    "tests/files/test_files_downloads.py::TestFilesDownloads.test_files_download_type_action"
)
DLP = "tests/files/test_files_scanning.py::TestFilesScanning.test_files_dlp_rule_enforced"


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("cache"))}}
    )
    index, _, _ = update_index(STANDIN, settings)
    return settings, index


def _draft(
    variants: list[dict[str, Any]], expected: str = "The file is converted."
) -> TestCaseDraft:
    return TestCaseDraft.model_validate(
        {
            "id": "X/d1",
            "ticket_id": "X",
            "kind": "primary",
            "intent": "A file type is handled by the download policy",
            "markers": {"priority": "p1", "component": "files", "suite": "regression"},
            "test_kind": "ui",
            "deployment_type": "both",
            "preconditions": [],
            "steps": ["Download the file"],
            "expected_outcome": expected,
            "variants": variants,
            "confidence": 0.9,
            "prompt_version": "x",
        }
    )


def _variant(name: str, expected: str, **inputs: str) -> dict[str, Any]:
    return {
        "name": name,
        "inputs": [{"name": k, "value": v} for k, v in inputs.items()],
        "expected": expected,
    }


def _decision(kind: str, target: str, target_file: str | None = None) -> ReuseDecision:
    return ReuseDecision(
        kind=kind,  # type: ignore[arg-type]
        domain="files",
        domain_uncertain=False,
        target=target,
        target_file=target_file,
        reasons=["test decision"],
    )


# --- the parametrize list -----------------------------------------------------------------------

ONE_LINE = """import pytest


class TestA:
    @pytest.mark.parametrize("kind", ["a", "b"])
    def test_x(self, kind):
        pass
"""


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ('["a", "b"]', '["a", "b", "c"]'),
        ("['a', 'b']", "['a', 'b', 'c']"),
        ('("a",)', '("a", "c",)'),
        (
            '[\n        "a",\n        "b",\n    ]',
            '[\n        "a",\n        "b",\n        "c",\n    ]',
        ),
        (
            '[\n        "a",\n        "b"\n    ]',
            '[\n        "a",\n        "b",\n        "c"\n    ]',
        ),
    ],
)
def test_a_value_is_appended_in_the_lists_own_style(values: str, expected: str) -> None:
    source = ONE_LINE.replace('["a", "b"]', values)
    site = parametrize_site(source, "TestA", "test_x")
    assert site.argname == "kind" and site.values[0] == "a"
    assert site.insert(source, ["c"]) == ONE_LINE.replace('["a", "b"]', expected)


@pytest.mark.parametrize(
    "decorator",
    [
        '@pytest.mark.parametrize("kind", ["a"], ids=["x"])',
        '@pytest.mark.parametrize("kind, other", [("a", 1)])',
        '@pytest.mark.parametrize("kind", KINDS)',
        '@pytest.mark.parametrize("kind", [1, 2])',
    ],
)
def test_lists_that_cant_be_patched_in_place_are_refused(decorator: str) -> None:
    source = ONE_LINE.replace('@pytest.mark.parametrize("kind", ["a", "b"])', decorator)
    with pytest.raises(PatchError):
        parametrize_site(source, "TestA", "test_x")


# --- variant plans ------------------------------------------------------------------------------


def test_a_plan_from_inputs_that_name_data_keys(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    chunk = next(c for c in index.chunks if c.id == TYPE_ACTION)
    source = (STANDIN / chunk.file_path).read_text(encoding="utf-8")
    site = parametrize_site(source, chunk.class_name, chunk.symbol_name)
    draft = _draft([_variant("docx file", "converted", file="notes.docx")])
    (plan,) = plan_variants_in_code(draft, chunk, site, settings) or []
    assert plan.case == "notes.docx"
    assert plan.base_case in ("html", "pdf")  # an entry whose outcome is "converted"
    # the expected response restates the file; the seeded files stay as they are
    assert [c.path for c in plan.changes] == ["file", "targets.0.response.0.file"]
    assert all(json.loads(c.value_json) == "notes.docx" for c in plan.changes)


def test_a_value_others_derive_from_needs_the_llm(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    chunk = next(c for c in index.chunks if c.id == DLP)
    source = (STANDIN / chunk.file_path).read_text(encoding="utf-8")
    site = parametrize_site(source, chunk.class_name, chunk.symbol_name)
    pattern = _draft([_variant("customer id", "blocked", pattern="CUST-\\d{6}")], "Blocked.")
    assert plan_variants_in_code(pattern, chunk, site, settings) is None  # content must match
    unknown = _draft([_variant("x", "blocked", sensitivity="high")])
    assert plan_variants_in_code(unknown, chunk, site, settings) is None  # names no key
    with pytest.raises(PatchError, match="needs the LLM"):
        variant_patch(pattern, _decision("variant", DLP), index, settings, STANDIN)


# --- variant patch ------------------------------------------------------------------------------


def test_a_variant_patch_in_code(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    draft = _draft([_variant("docx file", "converted", file="notes.docx")])
    generated = variant_patch(draft, _decision("variant", TYPE_ACTION), index, settings, STANDIN)
    assert generated.reuse_kind == "variant" and generated.attempts == 0
    assert generated.prompt_version == CODE_PLAN
    assert '"exe", "html", "pdf", "notes.docx"]' in generated.code
    new_id = "test_files_download_type_action[notes.docx]"
    assert new_id in generated.test_ids
    ids = [e["test_id"] for e in generated.data_entries]
    assert ids.index(new_id) == ids.index("test_files_download_type_action[pdf]") + 1
    code_diff, data_diff = (p.diff for p in generated.patches)
    assert code_diff.startswith("--- a/tests/files/")
    assert sum(line.startswith("+") for line in code_diff.splitlines()[2:]) == 1
    assert '+      "test_id":"test_files_download_type_action[notes.docx]",' in data_diff
    assert "-" not in [line[0] for line in data_diff.splitlines()[2:] if line]  # adds only
    assert validate_patch(generated, index, settings, STANDIN, draft).findings == []
    original = (STANDIN / "tests/files/test_files_downloads.py").read_text(encoding="utf-8")
    assert '"notes.docx"' not in original  # the target repo is never written


def test_a_variant_planned_by_the_llm(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    draft = _draft([_variant("customer id", "blocked", pattern="CUST-\\d{6}")], "Blocked.")
    reply = {
        "variants": [
            {
                "case": "customer_id",
                "base_case": "block",
                "changes": [
                    {"op": "set", "path": "policy.dlp.0.pattern", "value_json": '"CUST-\\\\d{6}"'},
                    {
                        "op": "set",
                        "path": "site.files.2.content",
                        "value_json": '"Customer CUST-123456 export"',
                    },
                ],
                "notes": "Confirm the content is scanned as text.",
            }
        ]
    }
    client = FakeLLMClient([json.dumps(reply)])
    generated = variant_patch(
        draft, _decision("variant", DLP), index, settings, STANDIN, client, "fake", "fake-model"
    )
    assert generated.attempts == 1 and generated.prompt_version == "variant_v1"
    entry = next(e for e in generated.data_entries if e["test_id"].endswith("[customer_id]"))
    assert entry["policy"]["dlp"][0]["pattern"] == "CUST-\\d{6}"
    assert entry["site"]["files"][2]["content"] == "Customer CUST-123456 export"
    assert "Confirm the content is scanned as text." in generated.review_checklist
    assert validate_patch(generated, index, settings, STANDIN, draft).findings == []


def test_llm_plans_are_checked(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    draft = _draft([_variant("x", "blocked", sensitivity="high")])
    bad = {
        "variants": [
            {
                "case": "block",  # already a case
                "base_case": "block",
                "changes": [{"op": "set", "path": "file", "value_json": '"a.txt"'}],
                "notes": "",
            }
        ]
    }
    with pytest.raises(PatchError, match="already a case"):
        variant_patch(
            draft,
            _decision("variant", DLP),
            index,
            settings,
            STANDIN,
            FakeLLMClient([json.dumps(bad)]),
        )
    bad["variants"][0].update(  # type: ignore[index]
        {"case": "new", "changes": [{"op": "set", "path": "nope.0.x", "value_json": "1"}]}
    )
    with pytest.raises(PatchError, match="not found in the base entry"):
        variant_patch(
            draft,
            _decision("variant", DLP),
            index,
            settings,
            STANDIN,
            FakeLLMClient([json.dumps(bad)]),
        )


# --- method patch -------------------------------------------------------------------------------

GENERATED_CLASS = '''import pytest

from framework.base_test import BaseTest
from framework.markers import component
from tests.files.checks import DownloadChecks


class TestFilesArchivesEncrypted(DownloadChecks):
   def setup(self):
      super().setup()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_files_archive_encrypted_members(self):
      """The viewer lists an unlocked archive's members."""
      self.nav.files.view_file(self.params["file"])
      self.check.assertEqual(self.params["members"], self.nav.files.viewer.content.splitlines())
'''


def test_new_methods_are_spliced_into_the_class(setup: tuple[Settings, IndexData]) -> None:
    settings, _index = setup
    source = (STANDIN / "tests/files/test_files_archives.py").read_text(encoding="utf-8")
    patched, added = splice_methods(source, "TestFilesArchives", GENERATED_CLASS, settings)
    assert added == ["test_files_archive_encrypted_members"]  # setup is the class's own
    assert patched.startswith(source)  # the class ends the file: nothing before it changes
    assert patched.count("def setup(") == source.count("def setup(")
    assert "import component" not in patched and "import BaseTest" not in patched  # unused
    assert patched.endswith(
        '      self.check.assertEqual(self.params["members"], '
        "self.nav.files.viewer.content.splitlines())\n"
    )
    assert '\n\n   @pytest.mark.priority("p2")\n' in patched  # the class's spacing and indent
    with pytest.raises(PatchError, match="no new test method"):
        splice_methods(
            source,
            "TestFilesArchives",
            GENERATED_CLASS.replace("test_files_archive_encrypted_members", "helper"),
            settings,
        )


def _generated(code: str, entries: list[dict[str, Any]]) -> GeneratedTest:
    return GeneratedTest(
        code=code,
        file_name="tests/files/test_files_archives_encrypted.py",
        data_file_name="tests/files/test_files_archives_encrypted.json",
        data_entries=entries,
        data_format="array",
        test_ids=[e["test_id"] for e in entries],
        template_entry_ref=None,
        ticket_id="X",
        draft_ref="X/d1",
        retrieved_chunk_ids=[],
        prompt_version="generate_v4",
        provider="fake",
        model="fake-model",
        attempts=1,
        context_tokens=0,
    )


def test_a_method_patch(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    path = "tests/files/test_files_archives.py"
    base = next(  # the class's viewer test: no backend check, like the new one
        e
        for c in index.chunks
        if c.symbol_name == "test_files_archive_view_members"
        for e in c.data_entries.values()
    )
    kept = {k: v for k, v in base.items() if k not in ("decision", "targets")}  # not read
    entry = {**kept, "test_id": "test_files_archive_encrypted_members", "members": ["a.txt"]}
    generated = method_patch(
        _generated(GENERATED_CLASS, [entry]),
        _decision("method", "TestFilesArchives", path),
        index,
        settings,
        STANDIN,
    )
    assert generated.reuse_kind == "method" and generated.file_name == path
    assert generated.data_entries[-1]["test_id"] == "test_files_archive_encrypted_members"
    assert "test_files_archive_encrypted_members" in generated.test_ids
    assert [p.path for p in generated.patches] == [path, path.replace(".py", ".json")]
    report = validate_patch(generated, index, settings, STANDIN)
    assert report.errors == [], [f.render() for f in report.errors]
    existing = {**entry, "test_id": base["test_id"]}
    with pytest.raises(PatchError, match="already exist"):
        method_patch(
            _generated(GENERATED_CLASS, [existing]),
            _decision("method", "TestFilesArchives", path),
            index,
            settings,
            STANDIN,
        )


def test_method_retrieval_puts_the_class_first(setup: tuple[Settings, IndexData]) -> None:
    _settings, index = setup
    other = TemplateRef(chunk_id=DLP, entry_key="test_files_dlp_rule_enforced[block]", why="x")
    retrieval = RetrievalResult(
        ticket_id="X", repo_root=".", query_text="", hits=[], templates=[other]
    )
    ranked = method_retrieval(
        retrieval, index, "TestFilesArchives", "tests/files/test_files_archives.py"
    )
    assert ranked.templates[0].chunk_id.startswith(
        "tests/files/test_files_archives.py::TestFilesArchives."
    )
    assert ranked.templates[-1] == other


# --- the reuse pipeline -------------------------------------------------------------------------


def _ticketed(settings: Settings, index: IndexData, draft: TestCaseDraft) -> RetrievalResult:
    from ticket2test.models.ticket import SourceInfo, Ticket
    from ticket2test.retrieve.pipeline import retrieve

    ticket = Ticket(
        id=draft.ticket_id,
        title=draft.intent,
        description=" ".join(draft.steps) + " " + draft.expected_outcome,
        source=SourceInfo(system="jira", ref=draft.ticket_id),
    )
    return retrieve(ticket, index, settings, None, draft)


def test_pipeline_covered_calls_no_llm(setup: tuple[Settings, IndexData]) -> None:
    from tests.test_reuse import SCENARIOS
    from ticket2test.generate.pipeline import generate_reusing

    settings, index = setup
    draft = SCENARIOS["covered"][0]
    fake = FakeLLMClient([])
    outcome = generate_reusing(
        draft, _ticketed(settings, index, draft), index, settings, fake, "fake", "m", STANDIN
    )
    assert outcome.kind == "covered" and outcome.generated is None and fake.requests == []
    assert outcome.decision.test_id == "test_files_download_type_action[exe]"


def test_pipeline_variant_with_an_llm_plan(setup: tuple[Settings, IndexData]) -> None:
    from tests.test_reuse import SCENARIOS
    from ticket2test.generate.pipeline import generate_reusing

    settings, index = setup
    draft = SCENARIOS["variant"][0]
    plan = {
        "case": "customer_id",
        "base_case": "block",
        "changes": [
            {"op": "set", "path": "policy.dlp.0.pattern", "value_json": '"CUST-\\\\d{6}"'},
            {"op": "set", "path": "site.files.2.content", "value_json": '"Order CUST-123456"'},
        ],
        "notes": "",
    }
    fake = FakeLLMClient([json.dumps({"variants": [plan]})])
    outcome = generate_reusing(
        draft, _ticketed(settings, index, draft), index, settings, fake, "fake", "m", STANDIN
    )
    assert outcome.kind == "variant" and outcome.generated is not None, outcome.notes
    assert len(fake.requests) == 1  # the plan only; no code generation
    assert outcome.report is not None and outcome.report.ok
    assert outcome.generated.reuse_target == DLP
    assert "test_files_dlp_rule_enforced[customer_id]" in outcome.generated.test_ids


def test_pipeline_forced_variant_falls_back(setup: tuple[Settings, IndexData]) -> None:
    from tests.test_reuse import SCENARIOS
    from ticket2test.generate.pipeline import generate_reusing

    settings, index = setup
    draft = SCENARIOS["method"][0]  # no variants: a case can't be planned in code
    fake = FakeLLMClient([])  # an LLM plan is attempted and fails; so does generation
    with pytest.raises(Exception, match="exhausted"):
        generate_reusing(
            draft,
            _ticketed(settings, index, draft),
            index,
            settings,
            fake,
            "fake",
            "m",
            STANDIN,
            mode="variant",
        )
    assert fake.requests and fake.requests[0].model is not None


def test_a_plan_value_that_isnt_json_is_sent_back(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    draft = _draft([_variant("customer id", "blocked", pattern="CUST-1")], "Blocked.")
    bad = {"op": "set", "path": "policy.dlp.0.pattern", "value_json": '"CUST-' + "\\" + 'd"'}
    good = {**bad, "value_json": json.dumps("CUST-" + "\\" + "d")}
    reply = {"case": "customer_id", "base_case": "block", "changes": [bad], "notes": ""}
    fake = FakeLLMClient(
        [
            json.dumps({"variants": [reply]}),
            json.dumps({"variants": [{**reply, "changes": [good]}]}),
        ]
    )
    generated = variant_patch(
        draft, _decision("variant", DLP), index, settings, STANDIN, fake, "fake", "m"
    )
    assert generated.attempts == 2 and "not valid JSON" in fake.requests[1].messages[-1].content
