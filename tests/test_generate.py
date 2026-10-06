"""Code generation (generate_v2) with the fake LLM: entries from the base entry, checks with
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
from ticket2test.models.retrieval import RetrievalResult, TemplateRef
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve

STANDIN = REPO_ROOT / "standin"
CONVENTIONS = (STANDIN / "CONVENTIONS.md").read_text(encoding="utf-8")
TEMPLATE_CHUNK = "tests/orders/test_orders.py::TestOrders.test_orders_detail_cancel"
TEMPLATE_ID = "test_orders_detail_cancel"
IDS = ("test_orders_detail_cancel_restock[1]", "test_orders_detail_cancel_restock[2]")

# As an LLM might write it: 4-space indent, annotations, imports out of order.
GOOD_CODE = '''"""Cancelling an order returns its stock."""

from __future__ import annotations

import pytest

from framework.decorators import browsers, environments
from framework.base_test import BaseTest


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@pytest.mark.project("example-project")
@pytest.mark.component("orders")
class TestOrdersDetailRestock(BaseTest):
    @pytest.mark.priority("p1")
    @pytest.mark.suite("regression")
    @pytest.mark.parametrize("units", [1, 2])
    def test_orders_detail_cancel_restock(self, params: dict, units: int) -> None:
        detail = self.nav.orders.order_detail
        detail.open_for(params["order_id"])
        detail.cancel()

        self.check.equal(detail.status, "cancelled", "order status")
        self.validate_backend(params)

    @pytest.mark.priority("p3")
    @pytest.mark.suite("regression")
    def test_orders_detail_cancel_button_label(self) -> None:
        detail = self.nav.orders.order_detail
        detail.open()
        self.check.equal(detail.status, "open", "order status")
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
        intent="Cancelling an open order sets it to cancelled and returns the stock.",
        markers={"priority": "p1", "component": "orders", "suite": "regression"},
        test_kind="ui",
        deployment_type="both",
        preconditions=["An open order for some units of an item"],
        steps=["Open the order", "Click Cancel order"],
        expected_outcome="The status is cancelled and the units are back in stock.",
        variants=[],
        confidence=0.9,
        prompt_version="draft_v1",
    )
    return TestCaseDraft.model_validate({**draft.model_dump(), **changes})


@pytest.fixture(scope="module")
def retrieval(index: IndexData, tmp_path_factory: pytest.TempPathFactory) -> RetrievalResult:
    """Retrieval for STND-104, with the cancel test pinned as the nearest template."""
    ticket = normalize(JiraExportSource(STANDIN / "tickets" / "export.json").fetch("STND-104"))
    result = retrieve(ticket, index, _settings(tmp_path_factory.mktemp("r")), None, _draft())
    pinned = TemplateRef(chunk_id=TEMPLATE_CHUNK, entry_key=TEMPLATE_ID, why="pinned for tests")
    others = [t for t in result.templates if t.chunk_id != TEMPLATE_CHUNK]
    return result.model_copy(update={"templates": [pinned, *others]})


def _change(path: str, value: Any = None, op: str = "set") -> dict[str, str]:
    return {"op": op, "path": path, "value_json": "" if op == "delete" else json.dumps(value)}


def _plan(test_id: str, units: int = 1, **kw: Any) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "copy_sections": kw.get("sections", ["settings", "policy", "targets", "interactions"]),
        "changes": kw.get(
            "changes",
            [
                _change("order_id", 1),
                _change("targets.orders.0.lines.0.quantity", units),
            ],
        ),
    }


def _reply(code: str = GOOD_CODE, plans: list[dict[str, Any]] | None = None, **kw: Any) -> str:
    return json.dumps(
        {
            "module_name": kw.get("module_name", "test_orders_detail_restock"),
            "code": code,
            "entries": [_plan(i, n) for n, i in enumerate(IDS, 1)] if plans is None else plans,
            "review_checklist": ["Confirm the stock count is shown without a refresh."],
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

    assert generated.test_ids == [*IDS, "test_orders_detail_cancel_button_label"]
    assert [e["id"] for e in generated.data_entries] == list(IDS)  # the label test reads nothing
    assert generated.data_format == "array"
    assert generated.file_name == "tests/orders/test_orders_detail_restock.py"
    assert generated.data_file_name == "tests/orders/test_orders_detail_restock.json"
    ref = generated.template_entry_ref
    assert ref is not None and (ref.chunk_id, ref.entry_key) == (TEMPLATE_CHUNK, TEMPLATE_ID)
    assert ref.chunk_id in generated.retrieved_chunk_ids
    assert generated.ticket_id == "STND-104" and generated.draft_ref == "STND-104/d1"
    assert generated.prompt_version == "generate_v2"
    assert (generated.provider, generated.model, generated.attempts) == ("fake", "fake-model", 1)
    assert generated.context_tokens > 0
    assert [p.test_id for p in generated.entry_plans] == list(IDS)
    defaults = Settings().generate.review_checklist_defaults
    assert generated.review_checklist == [
        *defaults,
        "Confirm the stock count is shown without a refresh.",
    ]


def test_entries_are_built_from_the_base_entry(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    generated = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply()]))
    base = _base(index)
    for units, entry in enumerate(generated.data_entries, 1):
        assert list(entry) == ["id", "settings", "policy", "targets", "interactions", "order_id"]
        assert entry["settings"] == base["settings"]  # copied verbatim
        # Re-labelled: the policy name embeds the test name.
        assert entry["policy"]["name"] == "policy-orders-detail-cancel-restock"
        assert {k: v for k, v in entry["policy"].items() if k != "name"} == {
            k: v for k, v in base["policy"].items() if k != "name"
        }
        assert entry["targets"]["orders"][0]["lines"][0]["quantity"] == units
        assert entry["interactions"] == base["interactions"]
    one, two = generated.data_entries
    assert {k: v for k, v in one.items() if k not in ("id", "targets")} == {
        k: v for k, v in two.items() if k not in ("id", "targets")
    }  # variants differ only in what varies
    assert base["targets"]["orders"][0]["lines"][0]["quantity"] == 2  # base untouched


def test_code_is_formatted_to_the_suite_style(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    code = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply()])).code
    lines = code.split("\n")
    assert "from __future__" not in code and "-> None" not in code and ": dict" not in code
    assert "   def test_orders_detail_cancel_restock(self, params, units):" in lines
    assert "      detail.cancel()" in lines
    imports = [line for line in lines if line.startswith(("import ", "from "))]
    assert imports == [
        "import pytest",
        "from framework.base_test import BaseTest",
        "from framework.decorators import browsers, environments",
    ]


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
    assert "Class scaffold (copy unchanged; new class name):" in user
    assert '@browsers("chrome", "firefox")\n@environments("cloud", "on_prem")' in user
    assert "class TestOrders(BaseTest):" in user
    assert "top-level sections: id, settings, policy, targets, interactions" in user
    assert '"name":"policy-orders-detail-cancel"' in user  # the suite's JSON style
    assert '@pytest.mark.priority("p1")' in user and "STND-104/d1" in user
    assert "Placeholder token for unique names: {{unique}}" in user
    assert "next to `tests/orders/test_orders.py`" in user


def test_class_scaffold_is_the_template_class_header(index: IndexData) -> None:
    chunk = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    assert class_scaffold(chunk, index) == (
        '@browsers("chrome", "firefox")\n'
        '@environments("cloud", "on_prem")\n'
        '@pytest.mark.project("example-project")\n'
        '@pytest.mark.component("orders")\n'
        "class TestOrders(BaseTest):"
    )


# --- checks with retry -----------------------------------------------------------------------


def _missing_key_plans() -> list[dict[str, Any]]:
    return [_plan(i, changes=[]) for i in IDS]


@pytest.mark.parametrize(
    ("bad", "fragment"),
    [
        (_reply(plans=[_plan(IDS[0])]), "read their data entry but have no entry"),
        (_reply(plans=_missing_key_plans()), "reads keys its entry lacks: ['order_id']"),
        (_reply(plans=[_plan(i, sections=["seed"]) for i in IDS]), "not sections of the base"),
        (_reply(plans=[_plan(i, sections=["skip"]) for i in IDS]), "not sections of the base"),
        (
            _reply(plans=[_plan(i, changes=[_change("targets.items.9.name", "x")]) for i in IDS]),
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
            _reply(code=GOOD_CODE.replace("TestOrdersDetailRestock", "TestOrders104")),
            "must not contain the ticket id",
        ),
        (_reply(module_name="OrdersTest"), "must look like test_area_action"),
        (_reply(code=GOOD_CODE.replace("[1, 2]", "UNITS")), "literals"),
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
    leaky = GOOD_CODE.replace('"""Cancelling', f'"""Token {token}. Cancelling')
    plans = [
        _plan(i, changes=[_change("order_id", 1), _change("auth", f"Bearer {'z' * 24}")])
        for i in IDS
    ]
    generated = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply(leaky, plans)]))
    assert token not in generated.code and "[REDACTED:github_token]" in generated.code
    for entry in generated.data_entries:
        assert entry["auth"] == "Bearer [REDACTED:bearer_token]"
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
        "id": "test_area_thing_save",
        "policy": {"name": "policy-area-thing-save", "rules": [{"id": "r1"}]},
        "targets": {"items": [{"name": "x-{{unique}}", "quantity": 1}]},
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
            ("set", "targets.items.0.quantity", "5"),
            ("set", "targets.items.1", '{"name": "y-{{unique}}"}'),
            ("delete", "policy.rules", ""),
            ("set", "label", '"Saved"'),
        ],
        per_entry_keys=["priority", "skip"],
    )
    assert entry == {
        "id": "test_area_thing_save_twice[a]",
        "policy": {"name": "policy-area-thing-save-twice"},
        "targets": {"items": [{"name": "x-{{unique}}", "quantity": 5}, {"name": "y-{{unique}}"}]},
        "custom": "test_area_thing_save_twice:label",
        "label": "Saved",
    }
    assert base["targets"]["items"][0]["quantity"] == 1  # deep copies
    with pytest.raises(EntryError, match="not sections"):
        build_entry(base, "b", "test_x", ["priority"], [], per_entry_keys=["priority"])
    with pytest.raises(EntryError, match="set automatically"):
        build_entry(base, "b", "test_x", [], [("set", "id", '"other"')])
    with pytest.raises(EntryError, match="not found"):
        build_entry(base, "b", "test_x", [], [("delete", "missing.key", "")])


def test_set_path_errors_name_the_step() -> None:
    target: dict[str, Any] = {"a": [1], "s": "text"}
    with pytest.raises(EntryError, match=r"a.3: index 3 is past the end"):
        set_path(target, "a.3", 1)
    with pytest.raises(EntryError, match=r"s.x: not an object"):
        set_path(target, "s.x", 1)
    with pytest.raises(EntryError, match="invalid path"):
        set_path(target, "a..b", 1)


def test_relabel_is_a_no_op_for_the_same_name() -> None:
    value = {"name": "policy-x-y"}
    assert relabel(value, "test_x_y", "test_x_y") == value


# --- context budget --------------------------------------------------------------------------


@pytest.mark.parametrize("budget", [3500, 4500, 6000, 9000, 12000, 30000])
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

    small, large = build(3500), build(30000)
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
        "component": "orders",
        "suite": "regression",
    }
    fuzzy = _draft(
        markers={"priority": "p2", "component": "order cancellation", "suite": "unknown"}
    )
    values = marker_values(fuzzy, Settings(), template, index)
    assert values["component"] == "orders"  # free text -> the template's value
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
    result = CliRunner().invoke(app, [*args, "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "Review checklist (needs a real run):" in result.output
    folder = out / "STND-104_d1"
    code = (folder / "tests/orders/test_orders_detail_restock.py").read_bytes()
    data = (folder / "tests/orders/test_orders_detail_restock.json").read_bytes().decode("utf-8")
    assert b"\r\n" not in code and code.startswith(b'"""Cancelling')
    entries = json.loads(data)
    assert [e["id"] for e in entries] == list(IDS)
    assert data == json.dumps(entries, indent=3, separators=(",", ":"), ensure_ascii=False) + "\n"
    assert (folder / "generated.json").is_file()
    assert (
        sorted(p.as_posix() for p in STANDIN.rglob("*") if "__pycache__" not in p.parts) == before
    )

    inside = CliRunner().invoke(app, [*args, "--out", str(STANDIN / "generated")])
    assert inside.exit_code == 2 and "outside the target repo" in inside.output
