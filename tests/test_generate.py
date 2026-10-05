"""Code generation with the fake LLM: context budget, entry assembly, checks, traceability."""

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
from ticket2test.generate.generator import (
    GenerationError,
    assemble_entry,
    build_generation_context,
    generate_test,
    marker_values,
)
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm import FakeLLMClient
from ticket2test.llm.structured import StructuredOutputError
from ticket2test.models import DraftResult, TestCaseDraft
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve

STANDIN = REPO_ROOT / "standin"
CONVENTIONS = (STANDIN / "CONVENTIONS.md").read_text(encoding="utf-8")

GOOD_CODE = '''"""Generated for STND-104: cancelling an order returns its stock."""

from __future__ import annotations

import pytest

from framework.base_test import BaseTest


@pytest.mark.project("example-project")
@pytest.mark.component("orders")
class TestStnd104(BaseTest):
    @pytest.mark.priority("P1")
    @pytest.mark.suite("regression")
    @pytest.mark.parametrize("units", [1, 2])
    def test_cancel_order_returns_stock(self, units: int) -> None:
        detail = self.nav.orders.order_detail.open_for(self.inputs["order_id"])
        detail.cancel()
        assert detail.status == "cancelled"
        self.assert_backend(self.expected["backend"])
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
        markers={"priority": "P1", "component": "orders", "suite": "regression"},
        test_kind="ui",
        deployment_type="both",
        preconditions=["An open order for 2 units of an item"],
        steps=["Open the order", "Click Cancel order"],
        expected_outcome="The status is cancelled and the units are back in stock.",
        variants=[],
        confidence=0.9,
        prompt_version="draft_v1",
    )
    return TestCaseDraft.model_validate({**draft.model_dump(), **changes})


@pytest.fixture(scope="module")
def retrieval(index: IndexData, tmp_path_factory: pytest.TempPathFactory) -> RetrievalResult:
    ticket = normalize(JiraExportSource(STANDIN / "tickets" / "export.json").fetch("STND-104"))
    return retrieve(ticket, index, _settings(tmp_path_factory.mktemp("r")), None, _draft())


def _entry(test_id: str, **parts: Any) -> dict[str, str]:
    seed = parts.get("seed", {"items": [{"name": "widget-{{unique}}", "quantity": 10}]})
    return {
        "test_id": test_id,
        "seed_json": json.dumps(seed),
        "inputs_json": json.dumps(parts.get("inputs", {"order_id": 1})),
        "expected_json": json.dumps(
            parts.get(
                "expected", {"backend": {"items": [{"name": "widget-{{unique}}", "quantity": 10}]}}
            )
        ),
    }


def _reply(
    code: str = GOOD_CODE,
    ids: tuple[str, ...] = (
        "test_cancel_order_returns_stock[1]",
        "test_cancel_order_returns_stock[2]",
    ),
    **parts: Any,
) -> str:
    return json.dumps({"code": code, "entries": [_entry(i, **parts) for i in ids], "notes": "ok"})


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


# --- happy path and traceability -------------------------------------------------------------


def test_generates_a_traceable_code_and_data_pair(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    fake = FakeLLMClient([_reply()])
    generated = _generate(index, retrieval, tmp_path, fake)

    assert generated.test_ids == [
        "test_cancel_order_returns_stock[1]",
        "test_cancel_order_returns_stock[2]",
    ]
    assert list(generated.data_entries) == generated.test_ids
    assert generated.file_name == "tests/orders/test_stnd_104.py"
    assert generated.data_file_name == "tests/orders/test_stnd_104.json"
    ref = generated.template_entry_ref
    assert ref is not None and ref.chunk_id in generated.retrieved_chunk_ids
    assert generated.ticket_id == "STND-104" and generated.draft_ref == "STND-104/d1"
    assert generated.prompt_version == "generate_v1"
    assert (generated.provider, generated.model, generated.attempts) == ("fake", "fake-model", 1)
    assert generated.retrieved_chunk_ids and generated.context_tokens > 0
    assert generated.code == GOOD_CODE


def test_config_block_is_copied_byte_identical(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    generated = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply()]))
    ref = generated.template_entry_ref
    assert ref is not None
    template_chunk = next(c for c in index.chunks if c.id == ref.chunk_id)
    template = template_chunk.data_entries[ref.entry_key]
    for entry in generated.data_entries.values():
        assert json.dumps(entry["config"], indent=2) == json.dumps(template["config"], indent=2)
        assert [k for k in entry if k in template] == [
            k for k in template if k not in ("priority", "skip")
        ]
        assert entry["inputs"] == {"order_id": 1}  # unique parts come from the LLM
        assert entry["seed"]["items"][0]["name"] == "widget-{{unique}}"


def test_prompt_contains_conventions_draft_template_and_markers(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    fake = FakeLLMClient([_reply()])
    _generate(index, retrieval, tmp_path, fake)
    user = fake.requests[0].messages[1].content
    assert "Team conventions for tests" in user and "Reach pages only through" in user
    assert "Template test:" in user and '"config"' in user
    assert (
        '@pytest.mark.priority("P1")' in user and '@pytest.mark.project("example-project")' in user
    )
    assert "STND-104/d1" in user
    assert "Placeholder token for unique names: {{unique}}" in user


# --- checks with retry -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "fragment"),
    [
        (_reply(ids=("test_cancel_order_returns_stock",)), "Missing entries"),
        (_reply(code=GOOD_CODE.replace("[1, 2]", "UNITS")), "literals"),
        (_reply(code="def broken(:\n"), "does not parse"),
        (_reply(code="x = 1\n", ids=()), "no test found"),
        (
            json.dumps(
                {
                    "code": GOOD_CODE,
                    "entries": [
                        {**_entry("test_cancel_order_returns_stock[1]"), "seed_json": "[1]"},
                        _entry("test_cancel_order_returns_stock[2]"),
                    ],
                    "notes": "",
                }
            ),
            "JSON object",
        ),
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
    leaky = GOOD_CODE.replace('"""Generated', f'"""Token {token}. Generated')
    fake = FakeLLMClient([_reply(code=leaky, inputs={"order_id": 1, "auth": f"Bearer {'z' * 24}"})])
    generated = _generate(index, retrieval, tmp_path, fake)
    assert token not in generated.code and "[REDACTED:github_token]" in generated.code
    for entry in generated.data_entries.values():
        assert entry["inputs"]["auth"] == "Bearer [REDACTED:bearer_token]"
    assert generated.redactions >= 3


def test_no_template_is_a_clean_error(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    empty = retrieval.model_copy(update={"templates": []})
    with pytest.raises(GenerationError, match="no template"):
        _generate(index, empty, tmp_path, FakeLLMClient([_reply()]))


# --- context budget --------------------------------------------------------------------------


@pytest.mark.parametrize("budget", [3000, 4500, 6000, 9000, 12000, 30000])
def test_context_never_exceeds_the_budget(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path, budget: int
) -> None:
    settings = _settings(tmp_path, max_tokens=budget)
    chunks = {c.id: c for c in index.chunks}
    template = chunks[retrieval.templates[0].chunk_id]
    built = build_generation_context(
        _draft(),
        retrieval,
        index,
        settings,
        template,
        retrieval.templates[0].entry_key,
        CONVENTIONS,
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
    chunks = {c.id: c for c in index.chunks}
    template = chunks[retrieval.templates[0].chunk_id]
    small = build_generation_context(
        _draft(),
        retrieval,
        index,
        _settings(tmp_path, max_tokens=3000),
        template,
        retrieval.templates[0].entry_key,
        CONVENTIONS,
    )
    large = build_generation_context(
        _draft(),
        retrieval,
        index,
        _settings(tmp_path, max_tokens=30000),
        template,
        retrieval.templates[0].entry_key,
        CONVENTIONS,
    )
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


# --- deterministic helpers -------------------------------------------------------------------


def test_assemble_entry_copies_shared_blocks_and_drops_overrides() -> None:
    template = {
        "config": {"environment": {"tenant": "t"}, "flags": [1, 2]},
        "seed": {"items": []},
        "inputs": {"a": 1},
        "expected": {"x": 1},
        "priority": "P3",
        "skip": {"ticket": "KEY-1", "reason": "r"},
        "extra": "kept",
    }
    entry = assemble_entry(
        template,
        {"seed": {"s": 1}, "inputs": {"b": 2}, "expected": {"y": 2}},
        ["seed", "inputs", "expected"],
        ["priority", "skip"],
    )
    assert list(entry) == ["config", "seed", "inputs", "expected", "extra"]
    assert entry["config"] == template["config"] and entry["inputs"] == {"b": 2}
    entry["config"]["environment"]["tenant"] = "changed"
    assert template["config"]["environment"]["tenant"] == "t"  # deep copy


def test_marker_values_use_known_values(index: IndexData, retrieval: RetrievalResult) -> None:
    chunks = {c.id: c for c in index.chunks}
    template = chunks[retrieval.templates[0].chunk_id]
    known = marker_values(_draft(), Settings(), template, index)
    assert known == {
        "priority": "P1",
        "project": "example-project",
        "component": "orders",
        "suite": "regression",
    }
    fuzzy = _draft(
        markers={"priority": "P2", "component": "order cancellation", "suite": "unknown"}
    )
    values = marker_values(fuzzy, Settings(), template, index)
    template_component = next(m.args[0] for m in template.markers if m.name == "component")
    assert values["component"] == template_component  # free text -> the template's value
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
    result = CliRunner().invoke(
        app,
        [
            "generate",
            str(tmp_path / "d.json"),
            "--retrieval",
            str(tmp_path / "r.json"),
            "--conventions",
            str(STANDIN / "CONVENTIONS.md"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    folder = out / "STND-104_d1"
    code = folder / "tests/orders/test_stnd_104.py"
    data = folder / "tests/orders/test_stnd_104.json"
    assert code.read_text("utf-8") == GOOD_CODE
    assert set(json.loads(data.read_text("utf-8"))) == {
        "test_cancel_order_returns_stock[1]",
        "test_cancel_order_returns_stock[2]",
    }
    assert (folder / "generated.json").is_file()
    assert (
        sorted(p.as_posix() for p in STANDIN.rglob("*") if "__pycache__" not in p.parts) == before
    )

    inside = CliRunner().invoke(
        app,
        [
            "generate",
            str(tmp_path / "d.json"),
            "--retrieval",
            str(tmp_path / "r.json"),
            "--out",
            str(STANDIN / "generated"),
        ],
    )
    assert inside.exit_code == 2 and "outside the target repo" in inside.output
