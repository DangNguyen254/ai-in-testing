"""Retrieval: query building, fusion, expansion, templates, capped follow-ups, and eval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import REPO_ROOT
from ticket2test.adapters.tickets.base import RawTicket
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.eval.pairs import EvalCache, load_pair_set
from ticket2test.eval.retrieval import (
    evaluate_retrieval,
    manifest_test_to_chunk_id,
    render_markdown,
)
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm import FakeLLMClient
from ticket2test.models import Ticket
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve
from ticket2test.retrieve.query import candidate_identifiers, verify_identifiers

STANDIN = REPO_ROOT / "standin"
EXPORT = STANDIN / "tickets" / "export.json"


def _settings(tmp_path: Path, **retrieval: Any) -> Settings:
    return Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path / "cache")}, "retrieval": retrieval}
    )


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    settings = _settings(tmp_path_factory.mktemp("idx"))
    data, _, _ = update_index(STANDIN, settings)
    return data


def _ticket(key: str) -> Ticket:
    return normalize(JiraExportSource(EXPORT).fetch(key))


def _rewrite(terms: list[str], identifiers: list[str]) -> str:
    return json.dumps({"terms": terms, "identifiers": identifiers, "reason": "r"})


def _followup(searches: list[dict[str, str]], done: bool = False) -> str:
    return json.dumps({"done": done, "searches": searches, "reason": "r"})


# --- query building -----------------------------------------------------------


def test_candidate_identifiers_and_verification(index: IndexData) -> None:
    text = (
        "Call `client.build_request()` with base_url; see ItemEditorPage and FooBarWidget. The end."
    )
    names = candidate_identifiers(text)
    for expected in (
        "client.build_request",
        "build_request",
        "base_url",
        "ItemEditorPage",
        "FooBarWidget",
    ):
        assert expected in names
    verified, rejected = verify_identifiers(
        ["ItemEditorPage", "FooBarWidget", "unique_name", "The"], index.catalog
    )
    assert verified == ["ItemEditorPage", "unique_name"]
    assert "FooBarWidget" in rejected and "The" in rejected


# --- deterministic pipeline ------------------------------------------------------------------


def test_every_hit_carries_reasons(index: IndexData, tmp_path: Path) -> None:
    result = retrieve(_ticket("STND-103"), index, _settings(tmp_path))
    assert len(result.hits) == 10
    assert result.llm_calls == 0 and result.rewrite is None
    for hit in result.hits:
        assert hit.reasons, hit.chunk_id
        assert {r.source for r in hit.reasons} <= {
            "bm25",
            "grep",
            "expansion",
            "followup",
            "template",
        }
    scores = [h.score for h in result.hits]
    assert scores == sorted(scores, reverse=True)


def test_expansion_adds_related_tests_and_page_objects(index: IndexData, tmp_path: Path) -> None:
    result = retrieve(_ticket("STND-101"), index, _settings(tmp_path, top_k=30))
    details = [r.detail for h in result.hits for r in h.reasons if r.source == "expansion"]
    assert any(d.startswith("page object used by ") for d in details)
    assert any(d.startswith(("test of ", "caller of ", "callee of ")) for d in details)


def test_templates_are_existing_entries(index: IndexData, tmp_path: Path) -> None:
    result = retrieve(_ticket("STND-104"), index, _settings(tmp_path))
    assert 1 <= len(result.templates) <= 3
    chunks = {c.id: c for c in index.chunks}
    for ref in result.templates:
        assert ref.entry_key in chunks[ref.chunk_id].data_entries


# --- LLM steps -------------------------------------------------------------------------------


def test_query_rewrite_terms_are_used_and_invented_names_rejected(
    index: IndexData, tmp_path: Path
) -> None:
    fake = FakeLLMClient(
        [_rewrite(["invite", "role", "editor"], ["InviteUserPage", "RoleAssigner"])]
    )
    result = retrieve(_ticket("STND-101"), index, _settings(tmp_path), fake)
    assert result.rewrite is not None and result.llm_calls == 1
    assert "InviteUserPage" in result.identifiers
    assert "RoleAssigner" in result.rejected_identifiers
    assert result.prompt_versions == ["query_rewrite_v1"]
    assert any(r.detail.startswith("query=rewrite") for h in result.hits for r in h.reasons)
    assert "<ticket>" in fake.requests[0].messages[1].content


def test_followup_rounds_stop_at_the_cap(index: IndexData, tmp_path: Path) -> None:
    # The fake never says "done" and always asks for new searches; results stay "thin".
    always_more = [_followup([{"tool": "bm25", "query": f"query {i}"}]) for i in range(10)]
    fake = FakeLLMClient([_rewrite(["x"], []), *always_more])
    settings = _settings(tmp_path, max_followup_rounds=2, followup_min_tests=999)
    result = retrieve(_ticket("STND-102"), index, settings, fake)
    assert result.followup_rounds == 2
    assert result.llm_calls == 3 and len(fake.requests) == 3  # 1 rewrite + exactly 2 rounds
    assert result.prompt_versions == ["query_rewrite_v1", "retrieval_followup_v1"]


_NEW_EACH_ROUND = ["invite", "cancel", "timezone", "digest", "quantity", "category"]


@pytest.mark.parametrize("rounds", [0, 1, 3])
def test_followup_cap_is_configurable(index: IndexData, tmp_path: Path, rounds: int) -> None:
    rounds_replies = [_followup([{"tool": "bm25", "query": q}]) for q in _NEW_EACH_ROUND]
    fake = FakeLLMClient([_rewrite(["x"], []), *rounds_replies])
    settings = _settings(tmp_path, top_k=40, max_followup_rounds=rounds, followup_min_tests=999)
    result = retrieve(_ticket("STND-102"), index, settings, fake)
    assert result.followup_rounds == rounds
    assert len(fake.requests) == 1 + rounds


def test_followup_stops_when_done_or_results_are_not_thin(index: IndexData, tmp_path: Path) -> None:
    fake = FakeLLMClient(
        [
            _rewrite(["x"], []),
            _followup([{"tool": "symbol", "query": "BaseTest"}], done=True),
            _followup([]),
        ]
    )
    result = retrieve(_ticket("STND-102"), index, _settings(tmp_path, followup_min_tests=999), fake)
    assert result.followup_rounds == 1

    not_thin = FakeLLMClient([_rewrite(["invite"], [])])
    result = retrieve(
        _ticket("STND-101"), index, _settings(tmp_path), not_thin
    )  # has tests in top_k
    assert result.followup_rounds == 0 and len(not_thin.requests) == 1


def test_followup_tools_are_limited_and_tagged(index: IndexData, tmp_path: Path) -> None:
    searches = [
        {"tool": "grep", "query": "assert_order_status"},
        {"tool": "grep", "query": "made_up_helper_name"},  # not in the repo: no results
        {"tool": "symbol", "query": "OrderDetailPage"},
        {"tool": "bm25", "query": "extra search beyond the cap"},
    ]
    fake = FakeLLMClient([_rewrite(["order"], []), _followup(searches, done=True)])
    settings = _settings(tmp_path, top_k=50, followup_min_tests=999, followup_max_searches=3)
    result = retrieve(_ticket("STND-104"), index, settings, fake)
    followup = [r.detail for h in result.hits for r in h.reasons if r.source == "followup"]
    assert any("identifier=assert_order_status" in d for d in followup)
    assert any("definition of OrderDetailPage" in d for d in followup)
    assert not any("made_up_helper_name" in d for d in followup)
    assert not any("beyond the cap" in d for d in followup)  # only the first 3 searches run


# --- eval ------------------------------------------------------------------------------------


def test_manifest_ids_map_to_chunk_ids() -> None:
    assert manifest_test_to_chunk_id("tests/a.py::TestA::test_x") == "tests/a.py::TestA.test_x"
    assert manifest_test_to_chunk_id("tests/a.py::test_x") == "tests/a.py::test_x"


def test_eval_standin_tests_ground_truth(tmp_path: Path) -> None:
    pair_set = load_pair_set(REPO_ROOT / "eval_data" / "standin_retrieval.json")
    report = evaluate_retrieval(pair_set, REPO_ROOT, _settings(tmp_path), client=None)
    assert len(report.pairs) == 6 and not report.skipped
    assert report.mean_recall is not None and 0.0 <= report.mean_recall <= 1.0
    assert report.mean_recall >= 0.5  # regression guard for the deterministic baseline
    assert "Mean recall@10" in render_markdown(report)


def test_eval_fix_pr_files_from_cache_without_network(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    cache = EvalCache(settings)
    raw = RawTicket(
        source="github",
        ref="demo/repo#7",
        payload={
            "issue": {
                "title": "Inviting a user as editor gives viewer role",
                "body": "Use InviteUserPage.invite",
                "labels": [],
                "comments": 0,
                "html_url": "https://github.com/demo/repo/issues/7",
            },
            "comments": [],
            "comments_complete": True,
        },
    )
    cache.ticket_path("demo/repo#7").parent.mkdir(parents=True)
    cache.ticket_path("demo/repo#7").write_text(raw.model_dump_json(), "utf-8")
    cache.pr_files_path("demo/repo", 8).parent.mkdir(parents=True)
    cache.pr_files_path("demo/repo", 8).write_text(
        json.dumps(["framework/pages/users.py", "docs/x.md", "gone.py"]), "utf-8"
    )
    spec = {
        "name": "demo",
        "repo_path": "standin",
        "ticket_source": "github",
        "ground_truth": "fix_pr_files",
        "pairs": [{"id": "demo-7", "ticket": "demo/repo#7", "fix_pr": 8}],
    }
    pair_set = load_pair_set(_write(tmp_path / "set.json", spec))
    report = evaluate_retrieval(pair_set, REPO_ROOT, settings, client=None, cache=cache)
    [pair] = report.pairs
    assert pair.unit == "file"
    assert pair.ground_truth == ["framework/pages/users.py"]
    assert pair.not_in_index == ["gone.py"]
    assert pair.recall == 1.0


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


_HTTPX_CACHE = REPO_ROOT / ".t2t_cache" / "eval" / "pr_files"


@pytest.mark.skipif(
    not ((REPO_ROOT / ".scratch/repos/httpx/httpx").is_dir() and _HTTPX_CACHE.is_dir()),
    reason="needs the httpx clone and the eval cache "
    "(run `ticket2test eval --set eval_data/httpx_retrieval.json` once)",
)
def test_httpx_baseline_from_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = Settings.model_validate({"paths": {"cache_dir": str(REPO_ROOT / ".t2t_cache")}})
    pair_set = load_pair_set(REPO_ROOT / "eval_data" / "httpx_retrieval.json")
    report = evaluate_retrieval(pair_set, REPO_ROOT, settings, client=None)
    assert len(report.pairs) >= 10
    assert report.mean_recall is not None and report.mean_recall >= 0.5


# --- CLI -------------------------------------------------------------------------------------


def test_cli_retrieve_and_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T2T_PATHS__CACHE_DIR", str(tmp_path / "cache"))
    ticket_file = tmp_path / "t.json"
    ticket_file.write_text(_ticket("STND-104").model_dump_json(), encoding="utf-8")
    out = tmp_path / "r.json"
    runner = CliRunner()
    result = runner.invoke(
        app, ["retrieve", str(ticket_file), "--repo", str(STANDIN), "--no-llm", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "10 hits" in result.output and " <- " in result.output
    assert json.loads(out.read_text("utf-8"))["hits"][0]["reasons"]

    monkeypatch.chdir(REPO_ROOT)
    report_dir = tmp_path / "reports"
    result = runner.invoke(
        app,
        ["eval", "--set", "eval_data/standin_retrieval.json", "--no-llm", "--out", str(report_dir)],
    )
    assert result.exit_code == 0, result.output
    assert len(list(report_dir.glob("standin-retrieval-*.json"))) == 1
    assert len(list(report_dir.glob("standin-retrieval-*.md"))) == 1

    other = runner.invoke(
        app, ["eval", "--set", "eval_data/standin_retrieval.json", "--stage", "e2e"]
    )
    assert other.exit_code == 1 and "Phase 8" in other.output
