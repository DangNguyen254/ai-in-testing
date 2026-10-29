"""Code generation (generate_v4) with the fake LLM: entries from the base entry, checks with
retry, formatting, context budget, traceability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import REPO_ROOT
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.generate.context import ContextBudgetError, Piece, build_context, estimate_tokens
from ticket2test.generate.entries import EntryError, build_entry, relabel, set_path
from ticket2test.generate.generator import (
    GenerationError,
    build_generation_context,
    class_scaffold,
    first_party,
    generate_test,
    marker_values,
)
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm import FakeLLMClient
from ticket2test.llm.structured import StructuredOutputError
from ticket2test.models import DraftResult, TestCaseDraft
from ticket2test.models.generated import GeneratedTest
from ticket2test.models.retrieval import RetrievalResult, TemplateRef
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve

STANDIN = REPO_ROOT / "standin"
CONVENTIONS = (STANDIN / "CONVENTIONS.md").read_text(encoding="utf-8")
TEMPLATE_CHUNK = "tests/rules/test_rules.py::TestRules.test_rules_delete_single"
TEMPLATE_ID = "test_rules_delete_single"
IDS = ("test_rules_delete_keeps_others[first]", "test_rules_delete_keeps_others[last]")
RULES = "{test_id:20}"

# As an LLM might write it: 4-space indent, annotations, imports out of order and unused.
GOOD_CODE = '''"""Deleting a rule and publishing keeps the other rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from framework.decorators import browsers, data_driven, environments
from framework.base_test import BaseTest


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("rules")
class TestRulesDelete(BaseTest):
    def setup(self) -> None:
        self.base_setup(fresh_driver=False, policy_wait=True)

    @pytest.mark.priority("p1")
    @pytest.mark.suite("regression")
    @pytest.mark.parametrize("position", ["first", "last"])
    def test_rules_delete_keeps_others(self, position: str) -> None:
        rules = self.nav.rules.list
        rules.open()
        rules.select_rule(self.params["delete_name"])
        rules.delete_selected()
        self.nav.rules.confirm.confirm()

        top_bar = self.nav.top_bar
        top_bar.save()
        top_bar.publish()
        self.verify_targets()

    @pytest.mark.priority("p3")
    @pytest.mark.suite("regression")
    def test_rules_delete_none_listed(self) -> None:
        rules = self.nav.rules.list
        rules.open()
        self.check.assertEqual(0, rules.total_count)
'''


def _settings(tmp_path: Path, **context: Any) -> Settings:
    return Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path / "cache")}, "context": context or {}}
    )


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    data, _, _ = update_index(STANDIN, _settings(tmp_path_factory.mktemp("idx")))
    return data


def _draft(**changes: Any) -> TestCaseDraft:
    draft = TestCaseDraft(
        id="STND-104/d1",
        ticket_id="STND-104",
        kind="primary",
        intent="Deleting a rule and publishing removes only that rule from the policy.",
        markers={"priority": "p1", "component": "rules", "suite": "regression"},
        test_kind="ui",
        deployment_type="both",
        preconditions=["A policy with three rules"],
        steps=["Select one rule", "Delete and confirm", "Save and publish"],
        expected_outcome="The published policy keeps only the other rules.",
        variants=[],
        prompt_version="draft_v1",
    )
    return TestCaseDraft.model_validate({**draft.model_dump(), **changes})


@pytest.fixture(scope="module")
def retrieval(index: IndexData, tmp_path_factory: pytest.TempPathFactory) -> RetrievalResult:
    """Retrieval for STND-104, with the delete test pinned as the nearest template."""
    ticket = normalize(JiraExportSource(STANDIN / "tickets" / "export.json").fetch("STND-104"))
    result = retrieve(ticket, index, _settings(tmp_path_factory.mktemp("r")), None, _draft())
    pinned = TemplateRef(chunk_id=TEMPLATE_CHUNK, entry_key=TEMPLATE_ID, why="pinned for tests")
    others = [t for t in result.templates if t.chunk_id != TEMPLATE_CHUNK]
    return result.model_copy(update={"templates": [pinned, *others]})


def _change(path: str, value: Any = None, op: str = "set") -> dict[str, str]:
    return {"op": op, "path": path, "value_json": "" if op == "delete" else json.dumps(value)}


_KEEP = {"first": ["b", "c"], "last": ["a", "b"]}
_DELETE = {"first": "a", "last": "c"}


def _plan(test_id: str, **kw: Any) -> dict[str, Any]:
    position = test_id.split("[")[1].rstrip("]") if "[" in test_id else "first"
    remaining = [{"name": f"{RULES}-{n}"} for n in _KEEP.get(position, ["b"])]
    return {
        "test_id": test_id,
        "copy_sections": kw.get("sections", ["settings", "policy", "delete_name", "targets"]),
        "changes": kw.get(
            "changes",
            [
                _change("delete_name", f"{RULES}-{_DELETE.get(position, 'a')}"),
                _change("targets.0.response", remaining),
            ],
        ),
    }


def _reply(code: str = GOOD_CODE, plans: list[dict[str, Any]] | None = None, **kw: Any) -> str:
    return json.dumps(
        {
            "module_name": kw.get("module_name", "test_rules_delete"),
            "code": code,
            "entries": [_plan(i) for i in IDS] if plans is None else plans,
            "review_checklist": ["Confirm the confirm page lists only the selected rule."],
            "notes": "ok",
        }
    )


def _generate(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path, fake: FakeLLMClient, **kw: Any
):  # type: ignore[no-untyped-def]
    return generate_test(
        kw.pop("draft", _draft()),
        retrieval,
        index,
        kw.pop("settings", _settings(tmp_path)),
        fake,
        provider="fake",
        model="fake-model",
        conventions=kw.pop("conventions", CONVENTIONS),
    )


def _base(index: IndexData) -> dict[str, Any]:
    chunk = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    entry: dict[str, Any] = chunk.data_entries[TEMPLATE_ID]
    return entry


# --- happy path and traceability -------------------------------------------------------------


def test_generates_a_traceable_code_and_data_pair(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    generated = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply()]))

    assert generated.test_ids == [*IDS, "test_rules_delete_none_listed"]
    # The UI-only test reads no data and calls no validation helper: no entry.
    assert [e["test_id"] for e in generated.data_entries] == list(IDS)
    assert generated.data_format == "array"
    assert generated.file_name == "tests/rules/test_rules_delete.py"
    assert generated.data_file_name == "tests/rules/test_rules_delete.json"
    ref = generated.template_entry_ref
    assert ref is not None and (ref.chunk_id, ref.entry_key) == (TEMPLATE_CHUNK, TEMPLATE_ID)
    assert ref.chunk_id in generated.retrieved_chunk_ids
    assert generated.ticket_id == "STND-104" and generated.draft_ref == "STND-104/d1"
    assert generated.prompt_version == "generate_v4"
    assert (generated.provider, generated.model, generated.attempts) == ("fake", "fake-model", 1)
    assert generated.context_tokens > 0
    assert [p.test_id for p in generated.entry_plans] == list(IDS)
    defaults = Settings().generate.review_checklist_defaults
    assert generated.review_checklist == [
        *defaults,
        "Confirm the confirm page lists only the selected rule.",
    ]


def test_entries_are_built_from_the_base_entry(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    generated = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply()]))
    base = _base(index)
    first, last = generated.data_entries
    for entry in generated.data_entries:
        assert list(entry) == ["test_id", "settings", "policy", "delete_name", "targets"]
        assert entry["settings"] == base["settings"] and entry["policy"] == base["policy"]
        assert entry["targets"][0]["path"] == base["targets"][0]["path"]  # request keys kept
        assert "skip" not in entry and "priority" not in entry
    assert (first["delete_name"], last["delete_name"]) == (f"{RULES}-a", f"{RULES}-c")
    assert last["targets"][0]["response"] == [{"name": f"{RULES}-a"}, {"name": f"{RULES}-b"}]
    differing = {k for k in first if first[k] != last[k]}
    assert differing == {"test_id", "delete_name", "targets"}  # only what varies
    assert base["delete_name"] == f"{RULES}-b"  # base untouched


def test_code_is_formatted_to_the_suite_style(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    code = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply()])).code
    lines = code.split("\n")
    assert "from __future__" not in code and "-> None" not in code and ": str" not in code
    assert "   def test_rules_delete_keeps_others(self, position):" in lines
    assert "      rules.delete_selected()" in lines
    imports = [line for line in lines if line.startswith(("import ", "from "))]
    assert imports == [
        "import pytest",
        "from framework.base_test import BaseTest",
        "from framework.decorators import browsers, data_driven, environments",
    ]  # sorted; the unused pathlib import is dropped


def test_first_party_roots_come_from_the_repo(index: IndexData) -> None:
    assert {"app", "framework"} <= set(first_party(index, Settings()))
    configured = Settings.model_validate({"style": {"python": {"first_party": ["mypkg"]}}})
    assert first_party(index, configured) == ["mypkg"]


def test_prompt_contains_conventions_scaffold_base_entry_and_markers(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    fake = FakeLLMClient([_reply()])
    _generate(index, retrieval, tmp_path, fake)
    user = fake.requests[0].messages[1].content
    assert "Team conventions for tests" in user and "No chaining" in user
    assert "Module imports and class scaffold (copy unchanged; new class name):" in user
    assert "from framework.decorators import browsers, data_driven, environments" in user
    assert "class TestRules(BaseTest):" in user
    assert (
        "   def setup(self):\n      self.base_setup(fresh_driver=False, policy_wait=True)" in user
    )
    assert "top-level sections: test_id, settings, policy, delete_name, targets" in user
    assert '"path":"/api/policy/v1/rules/:tid/:rev_id"' in user  # the suite's JSON style
    assert '@pytest.mark.priority("p1")' in user and "STND-104/d1" in user
    assert "Unique names in data: {test_id:24}" in user
    assert "next to `tests/rules/test_rules.py`" in user


def test_class_scaffold_has_imports_decorators_and_setup(index: IndexData) -> None:
    chunk = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    assert class_scaffold(chunk, index, ["setup", "teardown"]) == (
        "from pathlib import Path\n"
        "import pytest\n"
        "from framework.base_test import BaseTest\n"
        "from framework.decorators import "
        "browsers, data_driven, environments, retry, skip_browser\n"
        "\n"
        '@browsers("chrome", "firefox")\n'
        '@environments("cloud", "on_prem")\n'
        "@data_driven\n"
        '@pytest.mark.project("example-project")\n'
        '@pytest.mark.component("rules")\n'
        "class TestRules(BaseTest):\n"
        "   def setup(self):\n"
        "      self.base_setup(fresh_driver=False, policy_wait=True)"
    )
    tenants = next(c for c in index.chunks if c.class_name == "TestTenantsSecondary")
    scaffold = class_scaffold(tenants, index, ["setup", "teardown"])
    assert scaffold is not None and "   def teardown(self):\n      self.logout()" in scaffold


# --- checks with retry -----------------------------------------------------------------------


_NO_HELPER = GOOD_CODE.replace("        self.verify_targets()\n", "")


@pytest.mark.parametrize(
    ("bad", "fragment"),
    [
        (_reply(plans=[_plan(IDS[0])]), "use their data entry but have no entry"),
        (
            _reply(plans=[_plan(i, sections=["settings", "targets"], changes=[]) for i in IDS]),
            "reads keys its entry lacks: ['delete_name']",
        ),
        (_reply(plans=[_plan(i, sections=["seed"]) for i in IDS]), "not sections of the base"),
        (_reply(plans=[_plan(i, sections=["skip"]) for i in IDS]), "not sections of the base"),
        (
            _reply(
                plans=[_plan(i, changes=[_change("targets.0.response.9.name", "x")]) for i in IDS]
            ),
            "past the end",
        ),
        (
            _reply(
                plans=[
                    {**_plan(i), "changes": [{"op": "set", "path": "a", "value_json": "{nope"}]}
                    for i in IDS
                ]
            ),
            "not valid JSON",
        ),
        (_reply(plans=[*[_plan(i) for i in IDS], _plan("test_other[9]")]), "doesn't produce"),
        (_reply(module_name="test_stnd_104"), "must not contain the ticket id"),
        (
            _reply(code=GOOD_CODE.replace("TestRulesDelete", "TestRules104")),
            "must not contain the ticket id",
        ),
        (_reply(module_name="RulesTest"), "must look like test_area_action"),
        (_reply(code=GOOD_CODE.replace('["first", "last"]', "POSITIONS")), "literals"),
        (_reply(code="def broken(:\n"), "does not parse"),
        (_reply(code="x = 1\n", plans=[]), "no test found"),
    ],
)
def test_bad_output_is_retried_with_the_error(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path, bad: str, fragment: str
) -> None:
    fake = FakeLLMClient([bad, _reply()])
    generated = _generate(index, retrieval, tmp_path, fake)
    assert generated.attempts == 2
    assert fragment in fake.requests[1].messages[-1].content


@pytest.mark.parametrize(
    ("reply", "removed"),
    [
        (
            _reply(
                plans=[_plan(i, changes=[*_plan(i)["changes"], _change("extra", 1)]) for i in IDS]
            ),
            "extra",
        ),
        (_reply(code=_NO_HELPER), "targets"),  # the test never calls verify_targets()
        (
            _reply(
                plans=[
                    _plan(i, changes=[*_plan(i)["changes"], _change("interactions", [])])
                    for i in IDS
                ]
            ),
            "interactions",  # its helper isn't called; targets' is
        ),
    ],
)
def test_unread_keys_are_removed_in_code(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path, reply: str, removed: str
) -> None:
    fake = FakeLLMClient([reply])
    generated = _generate(index, retrieval, tmp_path, fake)
    assert generated.attempts == 1  # no LLM retry
    assert all(removed not in entry for entry in generated.data_entries)
    assert f"removed unread ['{removed}']" in generated.notes


def test_the_class_shell_comes_from_the_template(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    drifted = (
        GOOD_CODE.replace('@environments("cloud", "on_prem")\n', "")  # a decorator dropped
        .replace("class TestRulesDelete(BaseTest):", "class TestRulesDelete(object):")
        .replace("fresh_driver=False", "fresh_driver=True")  # another setup option
        .replace("@data_driven\n", "@data_driven\n@cloud_only\n")  # draft-specific: kept
        .replace(
            "from framework.base_test import BaseTest\n",
            "from framework.base_test import BaseTest\n"
            "from framework.decorators import cloud_only\n",
        )
    )
    generated = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply(code=drifted)]))
    code = generated.code
    assert "class TestRulesDelete(BaseTest):" in code
    assert '@environments("cloud", "on_prem")\n' in code
    assert "fresh_driver=False, policy_wait=True" in code  # the template class's setup
    assert "@cloud_only\n" in code and "cloud_only" in code.split("class ")[0]  # imported
    assert code.count("def test_") == GOOD_CODE.count("def test_")
    assert "class shell (imports, decorators, base, setup) from TestRules" in generated.notes


def test_one_mislabelled_entry_is_rekeyed_in_code(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    wrong = "test_rules_delete_keeps_others[middle]"
    fake = FakeLLMClient([_reply(plans=[_plan(IDS[0]), _plan(wrong)])])
    generated = _generate(index, retrieval, tmp_path, fake)
    assert generated.attempts == 1
    assert [e["test_id"] for e in generated.data_entries] == list(IDS)
    assert f"entry '{wrong}' re-keyed to '{IDS[1]}'" in generated.notes


def test_gives_up_after_the_retry_cap(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    fake = FakeLLMClient([_reply(code="nope(")] * 10)
    with pytest.raises(StructuredOutputError):
        _generate(index, retrieval, tmp_path, fake)
    assert len(fake.requests) == Settings().llm.max_retries_on_bad_json + 1


def test_secrets_in_the_output_are_scrubbed(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    token = "ghp_" + "Q1w2" * 9
    leaky = GOOD_CODE.replace('"""Deleting', f'"""Token {token}. Deleting')
    plans = [
        _plan(i, changes=[*_plan(i)["changes"], _change("delete_name", f"Bearer {'z' * 24}")])
        for i in IDS
    ]
    generated = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply(leaky, plans)]))
    assert token not in generated.code and "[REDACTED:github_token]" in generated.code
    for entry in generated.data_entries:
        assert entry["delete_name"] == "Bearer [REDACTED:bearer_token]"
    assert generated.redactions >= 3


def test_no_template_is_a_clean_error(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    empty = retrieval.model_copy(update={"templates": []})
    with pytest.raises(GenerationError, match="no template"):
        _generate(index, empty, tmp_path, FakeLLMClient([_reply()]))


# --- entry building (deterministic) ----------------------------------------------------------


def test_build_entry_copies_relabels_and_applies_changes() -> None:
    base = {
        "test_id": "test_area_thing_save",
        "policy": {"name": "policy-area-thing-save", "rules": [{"id": "r1"}]},
        "targets": [{"method": "GET", "path": "/api/x/:tid", "response": [{"n": 1}]}],
        "custom": "test_area_thing_save:label",
        "priority": "p3",
        "skip": {"ticket": "KEY-1", "reason": "r"},
    }
    entry = build_entry(
        base,
        "test_area_thing_save",
        "test_area_thing_save_twice[a]",
        ["policy", "targets", "custom"],
        [
            ("set", "targets.0.response.0.n", "5"),
            ("set", "targets.1", '{"method": "GET", "path": "/api/y/:tid", "response": {}}'),
            ("delete", "policy.rules", ""),
            ("set", "label", '"Saved"'),
        ],
        id_field="test_id",
        per_entry_keys=["priority", "skip"],
    )
    assert entry == {
        "test_id": "test_area_thing_save_twice[a]",
        "policy": {"name": "policy-area-thing-save-twice"},
        "targets": [
            {"method": "GET", "path": "/api/x/:tid", "response": [{"n": 5}]},
            {"method": "GET", "path": "/api/y/:tid", "response": {}},
        ],
        "custom": "test_area_thing_save_twice:label",
        "label": "Saved",
    }
    assert base["targets"][0]["response"][0]["n"] == 1  # deep copies
    with pytest.raises(EntryError, match="not sections"):
        build_entry(base, "b", "test_x", ["priority"], [], per_entry_keys=["priority"])
    with pytest.raises(EntryError, match="set automatically"):
        build_entry(base, "b", "test_x", [], [("set", "test_id", '"other"')], id_field="test_id")
    with pytest.raises(EntryError, match="not found"):
        build_entry(base, "b", "test_x", [], [("delete", "missing.key", "")])


def test_set_path_errors_name_the_step() -> None:
    target: dict[str, Any] = {"a": [1], "s": "text"}
    with pytest.raises(EntryError, match=r"a\.3: index 3 is past the end"):
        set_path(target, "a.3", 1)
    with pytest.raises(EntryError, match=r"s\.x: not an object"):
        set_path(target, "s.x", 1)
    with pytest.raises(EntryError, match="invalid path"):
        set_path(target, "a..b", 1)


def test_relabel_is_a_no_op_for_the_same_name() -> None:
    value = {"name": "policy-x-y"}
    assert relabel(value, "test_x_y", "test_x_y") == value


# --- context budget --------------------------------------------------------------------------


@pytest.mark.parametrize("budget", [5000, 6000, 9000, 12000, 30000])
def test_context_never_exceeds_the_budget(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path, budget: int
) -> None:
    settings = _settings(tmp_path, max_tokens=budget)
    chunks = {c.id: c for c in index.chunks}
    template = chunks[TEMPLATE_CHUNK]
    built = build_generation_context(
        _draft(), retrieval, index, settings, template, TEMPLATE_ID, CONVENTIONS
    )
    assert built.tokens <= budget
    assert estimate_tokens(built.render(), settings.context.chars_per_token) <= budget
    assert built.pieces[0].title == "Team conventions for tests"  # always included
    assert built.pieces[1].title.startswith("Template test:")
    for piece in built.pieces:
        if piece.chunk_id and piece.title.split(":")[0] in (
            "Similar test",
            "Page object",
            "Related code",
        ):
            assert chunks[piece.chunk_id].code in piece.body  # whole chunk, never cut


def test_bigger_budget_includes_more(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    template = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)

    def build(budget: int):  # type: ignore[no-untyped-def]
        return build_generation_context(
            _draft(),
            retrieval,
            index,
            _settings(tmp_path, max_tokens=budget),
            template,
            TEMPLATE_ID,
            CONVENTIONS,
        )

    small, large = build(5000), build(30000)
    assert len(large.pieces) > len(small.pieces) and small.skipped
    assert any(p.title.startswith("Base class: BaseTest") for p in large.pieces)


def test_build_context_skips_whole_pieces_and_keeps_order() -> None:
    pieces = [
        Piece("req", "r" * 300, required=True),
        Piece("big", "b" * 3000),
        Piece("small", "s" * 300),
    ]
    built = build_context(pieces, max_tokens=300, chars_per_token=3.0)
    assert [p.title for p in built.pieces] == ["req", "small"]
    assert built.skipped == ["big"]
    with pytest.raises(ContextBudgetError):
        build_context(
            [Piece("req", "r" * 3000, required=True)], max_tokens=100, chars_per_token=3.0
        )


def test_marker_values_use_known_values(index: IndexData) -> None:
    template = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    known = marker_values(_draft(), Settings(), template, index)
    assert known == {
        "priority": "p1",
        "project": "example-project",
        "component": "rules",
        "suite": "regression",
    }
    fuzzy = _draft(markers={"priority": "p2", "component": "rule deletion", "suite": "unknown"})
    values = marker_values(fuzzy, Settings(), template, index)
    assert values["component"] == "rules"  # free text -> the template's value
    assert values["suite"] in ("smoke", "regression")


# --- CLI -------------------------------------------------------------------------------------


def test_cli_generate_writes_the_pair_outside_the_repo(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("T2T_PATHS__CACHE_DIR", str(tmp_path / "cache"))
    drafts = DraftResult(
        ticket_id="STND-104",
        status="ok",
        drafts=[_draft()],
        prompt_version="draft_v1",
        provider="fake",
        model="m",
        attempts=1,
    )
    (tmp_path / "d.json").write_text(drafts.model_dump_json(), "utf-8")
    (tmp_path / "r.json").write_text(retrieval.model_dump_json(), "utf-8")
    fake = FakeLLMClient([_reply()])
    monkeypatch.setattr("ticket2test.llm.factory.create_llm_client", lambda *a, **k: fake)
    before = sorted(p.as_posix() for p in STANDIN.rglob("*") if "__pycache__" not in p.parts)

    out = tmp_path / "gen"
    args = ["generate", str(tmp_path / "d.json"), "--retrieval", str(tmp_path / "r.json")]
    result = CliRunner().invoke(app, [*args, "--out", str(out), "--as", "module"])
    assert result.exit_code == 0, result.output
    assert "Review checklist (needs a real run):" in result.output
    folder = out / "STND-104_d1"
    code = (folder / "tests/rules/test_rules_delete.py").read_bytes()
    data = (folder / "tests/rules/test_rules_delete.json").read_bytes().decode("utf-8")
    assert b"\r\n" not in code and code.startswith(b'"""Deleting')
    entries = json.loads(data)
    assert [e["test_id"] for e in entries] == list(IDS)
    assert data == json.dumps(entries, indent=3, separators=(",", ":"), ensure_ascii=False) + "\n"
    assert (folder / "generated.json").is_file()
    assert (
        sorted(p.as_posix() for p in STANDIN.rglob("*") if "__pycache__" not in p.parts) == before
    )

    inside = CliRunner().invoke(app, [*args, "--out", str(STANDIN / "generated")])
    assert inside.exit_code == 2 and "outside the target repo" in inside.output


def test_cli_generate_reuses_first(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("T2T_PATHS__CACHE_DIR", str(tmp_path / "cache"))
    drafts = DraftResult(
        ticket_id="STND-104",
        status="ok",
        drafts=[_draft()],
        prompt_version="draft_v1",
        provider="fake",
        model="m",
        attempts=1,
    )
    (tmp_path / "d.json").write_text(drafts.model_dump_json(), "utf-8")
    (tmp_path / "r.json").write_text(retrieval.model_dump_json(), "utf-8")
    fake = FakeLLMClient([_reply()])
    monkeypatch.setattr("ticket2test.llm.factory.create_llm_client", lambda *a, **k: fake)
    args = ["generate", str(tmp_path / "d.json"), "--retrieval", str(tmp_path / "r.json")]
    before = sorted(p.as_posix() for p in STANDIN.rglob("*") if "__pycache__" not in p.parts)
    result = CliRunner().invoke(app, [*args, "--out", str(tmp_path / "gen")])
    assert result.exit_code == 0, result.output
    assert "STND-104/d1: method" in result.output and "new method in TestRules" in result.output
    folder = tmp_path / "gen" / "STND-104_d1"
    generated = GeneratedTest.model_validate_json((folder / "generated.json").read_text("utf-8"))
    assert generated.reuse_kind == "method" and generated.reuse_target == "TestRules"
    assert generated.file_name == "tests/rules/test_rules.py"
    diff = (folder / "changes.patch").read_text("utf-8")
    assert "+++ b/tests/rules/test_rules.py" in diff and "+++ b/tests/rules/test_rules.json" in diff
    removed = [
        line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")
    ]
    assert removed == []  # adds a method and entries; changes nothing else
    patched = (folder / "patched/tests/rules/test_rules.py").read_text("utf-8")
    original = (STANDIN / "tests/rules/test_rules.py").read_text("utf-8")
    assert patched.startswith(original[: original.index("class TestRules")])
    assert all(i in generated.test_ids for i in IDS)
    assert json.loads((folder / "decision.json").read_text("utf-8"))["kind"] == "method"
    checked = CliRunner().invoke(app, ["validate", str(tmp_path / "gen"), "--repo", str(STANDIN)])
    assert checked.exit_code == 0 and "1/1 passed" in checked.output, checked.output
    assert (
        sorted(p.as_posix() for p in STANDIN.rglob("*") if "__pycache__" not in p.parts) == before
    )


def test_the_repair_loop_judges_attempts_with_the_given_check(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    """A new method in an existing class is judged inside that class: the check the pipeline
    passes decides, and with a clean report no repair round runs."""
    from ticket2test.validate.repair import generate_with_repair
    from ticket2test.validate.report import ValidationReport

    seen: list[str] = []

    def check(attempt):  # type: ignore[no-untyped-def]
        seen.append(attempt.file_name)
        return attempt, ValidationReport()

    fake = FakeLLMClient([_reply()])
    result = generate_with_repair(
        _draft(), retrieval, index, _settings(tmp_path), fake, "fake", "fake-model",
        CONVENTIONS, check=check,
    )  # fmt: skip
    assert seen and result.report.ok and result.report.repairs == 0
    assert fake.remaining == 0  # one generation call, no repair

    fallback = generate_with_repair(
        _draft(), retrieval, index, _settings(tmp_path), FakeLLMClient([_reply()]), "fake",
        "fake-model", CONVENTIONS, check=lambda attempt: None,
    )  # fmt: skip
    assert fallback.report.checks_run  # None: judged as a module, the usual validators ran
