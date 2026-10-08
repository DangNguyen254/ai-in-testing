"""Phase 8 eval harness: mining, leave-one-out, generation eval, report, consistency, CLI.

No network and no real LLM: tickets come from the stand-in's Jira export, the LLM is the fake,
and the sandbox is replaced where a test needs a collect result.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ticket2test.adapters.repo.git_history import GitHistoryReader
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.eval import generation as generation_module
from ticket2test.eval.generation import GenerationPairResult, GenerationReport, index_without
from ticket2test.eval.judge import JudgeVerdict
from ticket2test.eval.mining import mine_skip_removals
from ticket2test.eval.pairs import EvalPair, PairSet, load_pair_set
from ticket2test.eval.report import EvalRunReport, render_markdown
from ticket2test.eval.run import load_pair_sets, run_eval
from ticket2test.index.indexer import update_index
from ticket2test.llm.fake import FakeLLMClient
from ticket2test.retrieve.pipeline import retrieve
from ticket2test.sandbox.runner import CollectReport

from .test_draft import _item
from .test_draft import _reply as _draft_reply
from .test_generate import GOOD_CODE
from .test_generate import _reply as _generation_reply
from .test_retrieve import _rewrite

ROOT = Path(__file__).resolve().parents[1]
STANDIN = ROOT / "standin"
RULES = "tests/rules/test_rules.py::TestRules"


def _settings(tmp_path: Path, **retrieval: Any) -> Settings:
    return Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "retrieval": {"max_followup_rounds": 0, **retrieval},
            "sandbox": {"work_dir": str(tmp_path / "sandbox")},
        }
    )


# --- mining -------------------------------------------------------------------------------------


def _build_history(tmp_path: Path) -> Path:
    sys.path.insert(0, str(STANDIN / "tools"))
    try:
        build_history = importlib.import_module("build_history")
    finally:
        sys.path.remove(str(STANDIN / "tools"))
    repo: Path = build_history.build(tmp_path / "history")
    return repo


def test_mining_finds_the_code_skip_and_the_data_skip_fixes(tmp_path: Path) -> None:
    mined = mine_skip_removals(GitHistoryReader(_build_history(tmp_path)), Settings())
    assert [(m.ticket, m.test, m.kind) for m in mined] == [
        ("STND-103", f"{RULES}::test_rules_add_duplicate_name", "code_skip"),
        ("STND-104", f"{RULES}::test_rules_delete_single", "data_skip"),
        (
            "STND-117",
            "tests/files/test_files_archives.py::TestFilesArchives::test_files_archive_member_blocked",
            "data_skip",
        ),
    ]
    # STND-105 is still skipped (open bug): not mined.
    assert all(m.subject.startswith(f"Fix {m.ticket}") for m in mined)
    manifest = json.loads((STANDIN / "manifest.json").read_text(encoding="utf-8"))
    for m in mined:
        assert m.test in manifest["tickets"][m.ticket]["tests"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_mining_edge_cases(tmp_path: Path) -> None:
    """Class-level skips, object-keyed data files, and deleted tests (not re-enabled)."""
    repo = tmp_path / "r"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "tests" / "test_a.py").write_text(
        'import pytest\n\n\n@pytest.mark.skip(reason="ABC-1 broken")\nclass TestA:\n'
        "    def test_x(self):\n        pass\n\n\n"
        '@pytest.mark.skip(reason="ABC-2")\ndef test_gone():\n    pass\n\n\n'
        "def test_y():\n    pass\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_a.json").write_text(
        json.dumps({"test_y": {"skip": {"ticket": "ABC-3"}}}), encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "suite")
    (repo / "tests" / "test_a.py").write_text(
        "class TestA:\n    def test_x(self):\n        pass\n\n\ndef test_y():\n    pass\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_a.json").write_text(json.dumps({"test_y": {}}), encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "fixes")
    mined = mine_skip_removals(GitHistoryReader(repo), Settings())
    assert [(m.ticket, m.test, m.kind) for m in mined] == [
        ("ABC-1", "tests/test_a.py::TestA::test_x", "code_skip"),
        ("ABC-3", "tests/test_a.py::test_y", "data_skip"),
    ]  # ABC-2's test was deleted, not re-enabled


def test_git_reader_runs_only_read_commands(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    reader = GitHistoryReader(tmp_path, runner=runner)
    reader.commits(5)
    reader.changed_files("abc")
    reader.file_at("abc", "x.py")
    assert [a[4] for a in seen] == ["log", "diff-tree", "show"]
    assert "--max-count=5" in seen[0]
    public = {n for n in dir(GitHistoryReader) if not n.startswith("_")}
    assert public == {"commits", "changed_files", "file_at"}


# --- leave-one-out ------------------------------------------------------------------------------


def test_leave_one_out_removes_the_linked_test_from_retrieval(tmp_path: Path) -> None:
    from ticket2test.adapters.tickets.jira import JiraExportSource
    from ticket2test.normalize import normalize

    settings = _settings(tmp_path)
    index, _, _ = update_index(STANDIN, settings)
    linked = "tests/rules/test_rules.py::TestRules.test_rules_list_pagination"
    ticket = normalize(JiraExportSource(STANDIN / "tickets" / "export.json").fetch("STND-106"))
    full = retrieve(ticket, index, settings)
    assert linked in [h.chunk_id for h in full.hits]
    reduced = index_without(index, {linked})
    assert linked not in {c.id for c in reduced.chunks} and linked not in reduced.tokens
    assert len(reduced.chunks) == len(index.chunks) - 1
    result = retrieve(ticket, reduced, settings)
    assert linked not in [h.chunk_id for h in result.hits]
    assert linked not in [t.chunk_id for t in result.templates]


# --- generation eval (fake LLM, fake sandbox) --------------------------------------------------

_STND104 = PairSet(
    name="one",
    repo_path="standin",
    ticket_source="jira_export",
    jira_export="standin/tickets/export.json",
    conventions_doc="standin/CONVENTIONS.md",
    ground_truth="tests",
    generation=True,
    pairs=[
        EvalPair(
            id="standin-104",
            ticket="STND-104",
            tests=["tests/rules/test_rules.py::TestRules::test_rules_delete_single"],
        )
    ],
)
_DRAFT = _item(
    intent="Deleting a rule and publishing removes only that rule.",
    markers={"priority": "p1", "component": "rules", "suite": "regression"},
    test_kind="ui",
    variants=[],
    expected_outcome="The published policy keeps only the other rules.",
)
BAD_CODE = GOOD_CODE.replace("rules.total_count)", "rules.rule_count)")


def _fake_collect(ok: bool = True) -> Any:
    def collect(generated: Any, repo: Path, settings: Settings, **_: Any) -> CollectReport:
        return CollectReport(
            ok=ok,
            runtime="fake",
            image="fake",
            exit_code=0 if ok else 2,
            duration_seconds=0.1,
            expected=list(generated.test_ids),
            collected=list(generated.test_ids) if ok else [],
            output_tail="" if ok else "ImportError: boom",
        )

    return collect


def _generation_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replies: list[str], **kw: Any
) -> GenerationReport:
    monkeypatch.setattr(generation_module, "collect_generated", _fake_collect(kw.pop("ok", True)))
    settings = _settings(tmp_path)
    report = run_eval(
        [_STND104],
        ROOT,
        settings,
        FakeLLMClient(replies),
        stage="generation",
        leave_one_out=kw.pop("leave_one_out", False),
        keep_dir=tmp_path / "kept",
        **kw,
    ).generation
    assert report is not None
    return report


def test_generation_eval_measures_first_attempt_repair_and_collect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = [
        _draft_reply(_DRAFT),
        _rewrite(["delete", "rule"], []),
        _generation_reply(BAD_CODE),  # first attempt: an invented property
        _generation_reply(),  # repaired
    ]
    report = _generation_run(tmp_path, monkeypatch, replies)
    pair = report.pairs[0]
    assert pair.status == "generated" and pair.test_kind == "ui" and not pair.draft_cached
    assert pair.invented_names == 1 and pair.repairs == 1 and pair.final_ok
    assert any("rule_count" in e for e in pair.first_errors)
    assert pair.collect_ok is True and pair.llm_calls == 4
    metrics = report.metrics()
    assert metrics["first_attempt_pass_rate"] == 0.0 and metrics["final_pass_rate"] == 1.0
    assert metrics["invented_name_rate"] == 1.0 and metrics["collect_pass_rate"] == 1.0
    assert (tmp_path / "kept" / "standin-104" / "generated.json").is_file()


def test_cached_drafts_are_reused_and_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = [_draft_reply(_DRAFT), _rewrite(["delete"], []), _generation_reply()]
    _generation_run(tmp_path, monkeypatch, first)
    # Second run: no draft call (cached), so only rewrite + generation replies are needed.
    report = _generation_run(tmp_path, monkeypatch, [_rewrite(["delete"], []), _generation_reply()])
    assert report.pairs[0].draft_cached and report.pairs[0].llm_calls == 2
    fresh = [_draft_reply(_DRAFT), _rewrite(["delete"], []), _generation_reply()]
    report = _generation_run(tmp_path, monkeypatch, fresh, reuse_drafts=False)
    assert not report.pairs[0].draft_cached and report.pairs[0].llm_calls == 3


def test_insufficient_info_and_collect_failures_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vague = _draft_reply(status="insufficient_info", missing=["steps_to_reproduce"])
    report = _generation_run(tmp_path, monkeypatch, [vague], reuse_drafts=False)
    assert report.pairs[0].status == "insufficient_info"
    assert report.metrics()["insufficient_info"] == 1

    replies = [_draft_reply(_DRAFT), _rewrite(["delete"], []), _generation_reply()]
    report = _generation_run(tmp_path, monkeypatch, replies, ok=False, reuse_drafts=False)
    pair = report.pairs[0]
    assert pair.collect_ok is False and "ImportError" in pair.collect_note
    assert report.metrics()["collect_pass_rate"] == 0.0


def test_judge_results_are_kept_apart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = {
        "verdict": "partly",
        "score": 0.6,
        "unsupported": ["three rules"],
        "missing": [],
        "reason": "Adds a rule count.",
    }
    replies = [
        _draft_reply(_DRAFT),
        json.dumps(verdict),
        _rewrite(["delete"], []),
        _generation_reply(),
    ]
    report = _generation_run(tmp_path, monkeypatch, replies, judge=True, reuse_drafts=False)
    assert report.pairs[0].judge == JudgeVerdict(**verdict)  # type: ignore[arg-type]
    markdown = render_markdown(EvalRunReport(created_at=report.created_at, generation=report))
    measured, judged = markdown.split("## UNVALIDATED: LLM judge")
    assert "## Measured: generation" in measured and "partly" not in measured
    assert (
        "Not yet compared with human labels" in judged and "| STND-104 | partly | 0.60 |" in judged
    )


def test_report_without_judge_says_so() -> None:
    report = GenerationReport(
        set_name="s",
        created_at="2026-10-06T00:00:00Z",  # type: ignore[arg-type]
        leave_one_out=True,
        collect=False,
        judge=False,
        pairs=[GenerationPairResult(pair_id="p", ticket="T-1", status="failed", error="x")],
    )
    markdown = render_markdown(EvalRunReport(created_at=report.created_at, generation=report))
    assert "Not run (enable with `--judge`" in markdown
    assert report.metrics()["final_pass_rate"] is None  # nothing generated


# --- retrieval consistency, pair counts, CLI --------------------------------------------------


def test_deterministic_runs_are_identical_and_pairs_are_counted(tmp_path: Path) -> None:
    sets = load_pair_sets(ROOT / "eval_data")
    local = [s for s in sets if s.ticket_source == "jira_export"]  # no network
    report = run_eval(local, ROOT, _settings(tmp_path), None, stage="retrieval", runs=2)
    for runs in report.retrieval.values():
        first, second = runs
        assert first.mean_recall == second.mean_recall
        assert [p.retrieved for p in first.pairs] == [p.retrieved for p in second.pairs]
    assert [m.agrees for m in report.mined] == [True, True, True]
    total = sum(len(s.pairs) for s in sets)
    assert total >= 40 + 3  # 40 distinct pairs + 3 mined duplicates of manual links


def test_pair_sets_have_at_least_30_distinct_pairs() -> None:
    sets = load_pair_sets(ROOT / "eval_data")
    distinct = {
        (p.ticket, p.fix_pr if s.ground_truth == "fix_pr_files" else tuple(p.tests))
        for s in sets
        for p in s.pairs
    }
    assert len(distinct) >= 30
    assert any((p.source or "").startswith("mined") for s in sets for p in s.pairs)


def test_cli_mine_and_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)  # pair sets name paths relative to the project root
    monkeypatch.setenv("T2T_PATHS__CACHE_DIR", str(tmp_path / "cache"))
    runner = CliRunner()
    history = _build_history(tmp_path)
    out = tmp_path / "mined.json"
    result = runner.invoke(app, ["mine", str(history), "--out", str(out), "--repo-path", "standin"])
    assert result.exit_code == 0, result.output
    mined = load_pair_set(out)
    assert [p.ticket for p in mined.pairs] == ["STND-103", "STND-104", "STND-117"]

    result = runner.invoke(
        app,
        [
            "eval",
            "--set",
            str(ROOT / "eval_data" / "standin_retrieval.json"),
            "--no-llm",
            "--out",
            str(tmp_path / "reports"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "## Measured: retrieval" in result.output
    assert list((tmp_path / "reports").glob("eval-*.json"))
    result = runner.invoke(
        app,
        ["eval", "--set", str(ROOT / "eval_data" / "standin_retrieval.json"), "--stage",
         "generation", "--no-llm", "--out", str(tmp_path / "reports")],
    )  # fmt: skip
    assert result.exit_code == 1 and "needs the LLM" in result.output


def test_leave_one_out_copy_cuts_code_and_data(tmp_path: Path) -> None:
    from tests.conftest import REPO_ROOT
    from ticket2test.config import Settings
    from ticket2test.eval.generation import leave_one_out_repo
    from ticket2test.index.indexer import update_index
    from ticket2test.validate.suite import check_suite

    standin = REPO_ROOT / "standin"
    settings = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}})
    index, _, _ = update_index(standin, settings)
    cut = {  # the last test of its file (blank lines left behind) and one in the middle
        c.id
        for c in index.chunks
        if c.symbol_name in ("test_agent_api_settings_forbidden", "test_rules_list_pagination")
        and not c.inherited_from
    }
    copy = leave_one_out_repo(standin, index, cut, settings, tmp_path / "copy")
    other = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache2")}})
    copied, _, _ = update_index(copy, other)
    assert not cut & {c.id for c in copied.chunks}
    data = (copy / "tests/rules/test_rules.json").read_text(encoding="utf-8")
    assert "test_rules_list_pagination" not in data
    assert check_suite(copy, other).errors == 0  # code, data and style still agree
    assert "test_rules_list_pagination" in (standin / "tests/rules/test_rules.py").read_text(
        encoding="utf-8"
    )  # the original is only read
