"""The golden set's yardstick (design step 1): the reference scorer, pass@1 / pass^k, the
sheets, and the context report the C8 criterion reads."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ticket2test.config import Settings
from ticket2test.eval.generation import GenerationPairResult
from ticket2test.eval.golden import GoldenReport, GoldenRun, merge_c6, render_report, write_sheets
from ticket2test.eval.reference import block_paths, reference_facts, score
from ticket2test.index.indexer import IndexData
from ticket2test.models.generated import GeneratedTest, TemplateEntryRef
from ticket2test.models.retrieval import RetrievalResult

from .test_generate import STANDIN, TEMPLATE_CHUNK, TEMPLATE_ID
from .test_generate import index as index
from .test_generate import retrieval as retrieval

REFERENCE = "tests/rules/test_rules.py::TestRules::test_rules_delete_single"


def _as_generated(index: IndexData, code: str, names: list[str]) -> GeneratedTest:
    """The reference file itself as a "generated" patch adding the reference test."""
    chunk = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    entry = chunk.data_entries[TEMPLATE_ID]
    return GeneratedTest(
        code=code,
        file_name=chunk.file_path,
        data_file_name=chunk.data_file or "x.json",
        data_entries=[entry],
        data_format="array",
        test_ids=[TEMPLATE_ID],
        new_test_ids=[TEMPLATE_ID],
        template_entry_ref=TemplateEntryRef(chunk_id=TEMPLATE_CHUNK, entry_key=TEMPLATE_ID),
        ticket_id="X",
        draft_ref="X/d1",
        retrieved_chunk_ids=[],
        prompt_version="t",
        provider="fake",
        model="fake",
        attempts=1,
        context_tokens=0,
        context_names=names,
    )


def test_the_reference_scored_against_itself_passes_and_a_dropped_call_fails(
    index: IndexData,
) -> None:
    settings = Settings()
    chunk = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    source = index.files[chunk.file_path].info
    assert source is not None
    code = (STANDIN / chunk.file_path).read_text(encoding="utf-8")
    names = sorted({*code.replace("(", " ").replace(".", " ").split(), "policy", "targets"})
    names += [  # the context's identifiers include the entry's keys
        part
        for e in chunk.data_entries.values()
        for path in block_paths(e, "test_id")
        for part in path.replace("[]", ".").split(".")
    ]
    facts = reference_facts([REFERENCE], index, settings)
    same = score(_as_generated(index, code, names), facts, settings, [], True, None)
    assert (same.c1, same.c2, same.c3, same.c5, same.c7) == (True, True, True, True, True), same
    assert same.c2_recall == 1.0 and same.c3_recall == 1.0 and same.c8

    body = chunk.code
    first_call = next(line for line in body.splitlines() if "self." in line and "(" in line)
    dropped = code.replace(body, body.replace(first_call + "\n", "", 1), 1)  # in this test only
    assert dropped != code
    worse = score(_as_generated(index, dropped, names), facts, settings, [], True, None)
    assert not worse.c2 and worse.c2_recall < 1.0 and worse.missing_helpers
    made_up = ["[unsupported_values] payload: not from the ticket"]
    flagged = score(_as_generated(index, code, names), facts, settings, made_up, False, None)
    assert not flagged.c4 and not flagged.c7
    blind = score(_as_generated(index, code, []), facts, settings, [], True, None)
    assert not blind.c8 and blind.c8_helpers == 0.0


def test_block_paths_go_two_levels_deep() -> None:
    entry = {
        "test_id": "t",
        "policy": {"rules": [1], "agents": []},
        "targets": [{"url": "u", "expected": {"a": 1}}],
        "user": "x",
    }
    assert block_paths(entry, "test_id") == {
        "policy",
        "policy.rules",
        "policy.agents",
        "targets",
        "targets[].url",
        "targets[].expected",
        "user",
    }


def _run(pair: str, run: int, c1: bool, status: str = "generated") -> GoldenRun:
    result = GenerationPairResult(pair_id=pair, ticket=pair, status=status)
    return GoldenRun(pair_id=pair, run=run, result=result, scores={"c1": c1}, kept=f"/k/{pair}")


def test_pass_at_1_and_pass_hat_k(tmp_path: Path) -> None:
    report = GoldenReport(
        label="baseline-0",
        set_name="golden",
        created_at=datetime.now(UTC),
        repeat=3,
        runs=[
            _run("a", 1, True),
            _run("a", 2, True),
            _run("a", 3, True),
            _run("b", 1, True),
            _run("b", 2, False),
            _run("b", 3, True, status="failed"),
        ],
    )
    summary = report.summary()
    assert summary["c1"] == {"pass@1": round(4 / 6, 3), "pass^k": 0.5}
    assert summary["c6"] == {"pass@1": None, "pass^k": None}
    written = write_sheets(report, tmp_path)
    assert {p.name for p in written} == {"c6.csv", "open-coding.md"}
    sheet = tmp_path / "c6.csv"
    rows = sheet.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + 5  # header + the generated runs
    sheet.write_text(
        "\n".join([rows[0], *(r + ("yes" if i % 2 else "no") for i, r in enumerate(rows[1:]))])
        + "\n",
        encoding="utf-8",
    )
    assert merge_c6(report, sheet) == 5
    assert report.summary()["c6"]["pass@1"] is not None
    assert "| C6 checks cover the outcome (person) |" in render_report(report)
    assert write_sheets(report, tmp_path) == []  # never overwrites a person's answers


def test_a_generation_records_what_its_context_held(
    index: IndexData, retrieval: RetrievalResult, tmp_path: Path
) -> None:
    """C8 reads it: every piece offered with its tokens and whether it was kept, and the
    identifiers of the kept pieces."""
    from ticket2test.llm import FakeLLMClient

    from .test_generate import _generate, _reply

    generated = _generate(index, retrieval, tmp_path, FakeLLMClient([_reply()]))
    titles = [p.title for p in generated.context_report]
    assert any(t.startswith("Template test:") for t in titles)
    assert all(p.tokens > 0 for p in generated.context_report)
    assert any(p.kept and p.required for p in generated.context_report)
    assert "verify_targets" in generated.context_names


def test_a_golden_run_repeats_each_ticket_and_scores_every_run(tmp_path: Path) -> None:
    """The stand-in ticket twice, its reference hidden: two scored runs, the draft made once
    (cached for the second run), each run's output kept in its own folder."""
    from ticket2test.eval.golden import run_golden
    from ticket2test.llm.fake import FakeLLMClient

    from .test_eval_harness import (
        _DRAFT,
        _STND104,
        ROOT,
        _draft_reply,
        _generation_reply,
        _rewrite,
        _settings,
    )

    replies = [
        _draft_reply(_DRAFT),
        _rewrite(["delete", "rule"], []),
        _generation_reply(),
        _rewrite(["delete", "rule"], []),
        _generation_reply(),
    ]
    # another test as the reference: hiding it leaves the canned reply's template in place
    pair = _STND104.pairs[0].model_copy(
        update={"tests": ["tests/rules/test_rules.py::TestRules::test_rules_add_with_condition"]}
    )
    golden_set = _STND104.model_copy(update={"pairs": [pair]})
    lines: list[str] = []
    report = run_golden(
        golden_set,
        ROOT,
        _settings(tmp_path),
        FakeLLMClient(replies),
        2,
        "smoke",
        tmp_path / "runs",
        progress=lines.append,
    )
    assert any(line.startswith("run 2/2 standin-104 r2: generated") for line in lines), lines
    assert [(r.pair_id, r.run) for r in report.runs] == [("standin-104", 1), ("standin-104", 2)]
    assert all(r.result.status == "generated" for r in report.runs), report.runs[0].result.error
    assert all(Path(r.kept, "generated.json").is_file() for r in report.runs)
    first = report.runs[0].scores
    assert {"c1", "c2", "c3", "c8", "c2_recall"} <= set(first) and first["note"] == ""
    assert report.summary()["c7"]["pass^k"] is not None
    assert report.config["generate.context_helpers"] is True


def test_the_oracle_template_pins_the_reference_class_nearest_test(
    tmp_path: Path, index: IndexData, retrieval: RetrievalResult
) -> None:
    """``eval.oracle_template`` (a diagnostic): the reference class's nearest remaining test goes
    first among the templates, whatever search ranked; a class with no test left pins nothing."""
    from ticket2test.eval.generation import pin_template
    from ticket2test.eval.golden import config_snapshot, run_golden
    from ticket2test.llm.fake import FakeLLMClient
    from ticket2test.models.retrieval import TemplateRef

    from .test_eval_harness import _DRAFT, ROOT, _draft_reply, _settings
    from .test_generate import _draft

    settings = _settings(tmp_path)
    assert config_snapshot(settings)["eval.oracle_template"] is False
    golden_set, _, one_run = _golden_smoke(tmp_path)
    settings.eval.oracle_template = True
    lines: list[str] = []
    report = run_golden(
        golden_set, ROOT, settings, FakeLLMClient([_draft_reply(_DRAFT), *one_run]), 1, "pin",
        tmp_path / "runs", progress=lines.append,
    )  # fmt: skip
    assert any(line.endswith("template pinned: yes") for line in lines), lines
    assert report.config["eval.oracle_template"] is True

    draft = _draft()
    other = next(c for c in index.chunks if c.kind == "test" and c.class_name != "TestRules")
    search = TemplateRef(chunk_id=other.id, entry_key=None, why="search")
    found = retrieval.model_copy(update={"templates": [search]})
    pinned = pin_template(found, index, ("tests/rules/test_rules.py", "TestRules"), draft, settings)
    assert pinned is not None and pinned.templates[1].chunk_id == other.id
    first = next(c for c in index.chunks if c.id == pinned.templates[0].chunk_id)
    assert first.class_name == "TestRules" and pinned.templates[0].entry_key in first.data_entries
    assert (
        pin_template(found, index, ("tests/rules/test_rules.py", "Gone"), draft, settings) is None
    )


def test_the_oracle_steps_give_the_generator_the_reference_calls(tmp_path: Path) -> None:
    """``eval.oracle_steps`` (a diagnostic): the calls the reference test makes are in the
    generator's prompt, and nowhere when the switch is off."""
    from ticket2test.eval.generation import steps_context
    from ticket2test.eval.golden import config_snapshot, run_golden
    from ticket2test.llm.fake import FakeLLMClient

    from .test_eval_harness import _DRAFT, ROOT, _draft_reply, _settings

    marker = steps_context([])[:40]
    assert config_snapshot(_settings(tmp_path))["eval.oracle_steps"] is False
    for on in (False, True):
        folder = tmp_path / f"on-{on}"
        folder.mkdir()
        golden_set, settings, one_run = _golden_smoke(folder)
        settings.eval.oracle_steps = on
        client = FakeLLMClient([_draft_reply(_DRAFT), *one_run])
        lines: list[str] = []
        report = run_golden(
            golden_set, ROOT, settings, client, 1, "steps", folder / "runs", progress=lines.append
        )
        prompts = [m.content for r in client.requests for m in r.messages]
        assert any(marker in p for p in prompts) is on
        assert any("calls given:" in line for line in lines) is on
        assert report.config["eval.oracle_steps"] is on
        if on:
            assert any("- `self." in p for p in prompts if marker in p)


def test_a_page_action_reached_another_way_counts_as_called(index: IndexData) -> None:
    """Found in the first real baseline: a third of the "missing" calls were in the new test,
    reached through another local or chain spelling. Calls compare by what they resolve to:
    the class the chain leads to and the member."""
    from ticket2test.eval.reference import call_key

    settings = Settings()
    chunk = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    code = (STANDIN / chunk.file_path).read_text(encoding="utf-8")
    facts = reference_facts([REFERENCE], index, settings)
    assert facts is not None
    resolved = call_key("nav.rules.list.open", "TestRules", index)
    assert resolved.endswith(".open") and not resolved.startswith("nav.")
    body = chunk.code
    new_body = body.replace(
        "      rules = self.nav.rules.list\n",
        "      nav = self.nav\n      rules = nav.rules.list\n",
        1,
    )
    assert new_body != body  # the reference test itself is respelled
    respelled = code.replace(body, new_body, 1)
    assert respelled != code
    names = sorted(set(code.replace("(", " ").replace(".", " ").split()))
    generated = _as_generated(index, respelled, names)
    found = score(generated, facts, settings, [], True, None, index)
    assert found.c2 and found.c2_recall == 1.0, found.missing_helpers


def test_only_the_named_pairs_run() -> None:
    import pytest

    from ticket2test.eval.golden import select_pairs

    from .test_eval_harness import _STND104

    two = _STND104.model_copy(
        update={"pairs": [*_STND104.pairs, _STND104.pairs[0].model_copy(update={"id": "g2"})]}
    )
    assert [p.id for p in select_pairs(two, None).pairs] == ["standin-104", "g2"]
    assert [p.id for p in select_pairs(two, ["g2"]).pairs] == ["g2"]
    assert [p.id for p in select_pairs(two, ["g2,standin-104"]).pairs] == ["standin-104", "g2"]
    with pytest.raises(ValueError, match="no pair g3"):
        select_pairs(two, ["g3"])


def test_a_new_file_is_right_when_the_reference_was_its_class_s_only_test(
    index: IndexData,
) -> None:
    """Found in the first real baseline: two references were the only tests of their classes,
    so hiding them left nothing to point the tool there; a new file next to them is the right
    placement, not a miss."""
    settings = Settings()
    chunk = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    others = {
        c.id
        for c in index.chunks
        if c.kind == "test" and c.file_path == chunk.file_path and c.class_name == chunk.class_name
    }
    alone = reference_facts([REFERENCE], index, settings, others)
    with_siblings = reference_facts([REFERENCE], index, settings, set())
    assert alone is not None and alone.new_class_expected
    assert with_siblings is not None and not with_siblings.new_class_expected
    code = (STANDIN / chunk.file_path).read_text(encoding="utf-8")
    folder = chunk.file_path.rsplit("/", 1)[0]
    module = _as_generated(index, code, []).model_copy(
        update={"reuse_kind": "module", "file_name": f"{folder}/test_new_area.py"}
    )
    assert score(module, alone, settings, [], True, None).c1
    assert not score(module, with_siblings, settings, [], True, None).c1
    elsewhere = module.model_copy(update={"file_name": "tests/other/test_new_area.py"})
    assert not score(elsewhere, alone, settings, [], True, None).c1


def test_a_misplaced_run_says_why_without_names(index: IndexData) -> None:
    """From experiment 1: the reasons alone didn't show whether the reference's class lost the
    class match or was never in the chosen area; the run records the decision, C1 reads it."""
    settings = Settings()
    facts = reference_facts([REFERENCE], index, settings)
    assert facts is not None
    key = f"{facts.file_path}::{facts.class_name}"
    folder = facts.file_path.rsplit("/", 1)[0]
    wrong = _as_generated(index, "x = 1\n", []).model_copy(
        update={"file_name": "tests/other/test_x.py"}
    )

    def why(placement: dict[str, object] | None) -> str:
        g = wrong.model_copy(update={"reuse_placement": placement})
        return score(g, facts, settings, [], True, None).c1_why

    assert why(None) == "no placement recorded"
    assert why({"domain_folders": ["tests/other"]}) == "area"
    base = {"domain_folders": [folder]}
    assert why({**base, "excluded": {key: "gated"}}) == "excluded"
    assert why({**base, "class_scores": {"a::B": 0.5}}) == "not a candidate"
    assert why({**base, "class_scores": {"a::B": 0.5, key: 0.2}}) == (
        "rank 2/2 (0.20 vs 0.50); no template in the area"
    )


def _golden_smoke(tmp_path: Path) -> tuple[Any, Settings, list[str]]:
    """The stand-in ticket as a golden set, its settings, and one run's model replies."""
    from .test_eval_harness import _STND104, _generation_reply, _rewrite, _settings

    pair = _STND104.pairs[0].model_copy(
        update={"tests": ["tests/rules/test_rules.py::TestRules::test_rules_add_with_condition"]}
    )
    one_run = [_rewrite(["delete", "rule"], []), _generation_reply()]
    return _STND104.model_copy(update={"pairs": [pair]}), _settings(tmp_path), one_run


def test_a_tickets_runs_can_be_made_at_the_same_time(tmp_path: Path) -> None:
    """``eval.golden_parallel``: a ticket's runs go to the model together, each kept in its own
    folder, scored and counted like runs made in turn."""
    import threading
    import time

    from ticket2test.eval.golden import run_golden
    from ticket2test.llm.base import LLMClient, LLMRequest, LLMResponse

    from .test_eval_harness import _DRAFT, ROOT, _draft_reply

    golden_set, settings, (rewrite, generation) = _golden_smoke(tmp_path)
    settings.eval.golden_parallel = 2

    class ByKind(LLMClient):
        """Answers by what is asked (runs made together ask in no fixed order)."""

        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.now = self.most = self.calls = 0

        def complete(self, request: LLMRequest) -> LLMResponse:
            with self.lock:
                self.now += 1
                self.calls += 1
                self.most = max(self.most, self.now)
            time.sleep(0.2)  # long enough for the other run's call to overlap
            with self.lock:
                self.now -= 1
            fields = set((request.json_schema or {}).get("properties", {}))
            text = generation if "code" in fields else _draft_reply(_DRAFT)
            if "drafts" not in fields and "code" not in fields:
                text = rewrite
            return LLMResponse(text=text, model="fake-model", cost_usd=0.01)

    client = ByKind()
    report = run_golden(golden_set, ROOT, settings, client, 2, "together", tmp_path / "runs")
    assert client.most == 2  # two calls were in flight at once
    assert [(r.pair_id, r.run) for r in report.runs] == [("standin-104", 1), ("standin-104", 2)]
    assert all(r.result.status == "generated" for r in report.runs)
    kept = [Path(r.kept) for r in report.runs]
    assert kept[0] != kept[1] and all((k / "generated.json").is_file() for k in kept)
    assert all((k / "retrieval.json").is_file() for k in kept)
    assert not list((tmp_path / "runs").rglob(".stage-*"))
    assert report.usage is not None and report.usage.calls == client.calls  # none lost
    assert report.runs[0].scores == report.runs[1].scores


def test_a_stopped_golden_run_continues_from_its_report(tmp_path: Path) -> None:
    """A run cut short in its second run (a lost connection, Ctrl+C): the report on disk holds
    the first, and resuming makes only the second; the totals add up over both sessions. Each
    run's retrieval is kept next to its output."""
    from ticket2test.eval.golden import GoldenReport, run_golden
    from ticket2test.llm.base import LLMRequest, LLMResponse
    from ticket2test.llm.fake import FakeLLMClient

    from .test_eval_harness import _DRAFT, ROOT, _draft_reply

    golden_set, settings, one_run = _golden_smoke(tmp_path)

    class Cut(FakeLLMClient):
        def complete(self, request: LLMRequest) -> LLMResponse:
            if not self.remaining:
                raise KeyboardInterrupt
            return super().complete(request)

    checkpoint = tmp_path / "report.json"
    with pytest.raises(KeyboardInterrupt):
        run_golden(
            golden_set, ROOT, settings, Cut([_draft_reply(_DRAFT), *one_run]), 2, "smoke",
            tmp_path / "runs", checkpoint=checkpoint,
        )  # fmt: skip
    saved = GoldenReport.model_validate_json(checkpoint.read_text(encoding="utf-8"))
    assert [(r.pair_id, r.run) for r in saved.runs] == [("standin-104", 1)]
    assert saved.runs[0].result.status == "generated" and saved.llm_calls == 3
    assert Path(saved.runs[0].kept, "retrieval.json").is_file()

    lines: list[str] = []
    rest = FakeLLMClient(one_run)  # the draft is cached, run 1 isn't made again
    report = run_golden(
        golden_set, ROOT, settings, rest, 2, "ignored", tmp_path / "runs",
        progress=lines.append, checkpoint=checkpoint, resume=saved,
    )  # fmt: skip
    assert rest.remaining == 0 and any(line.startswith("run 2/2 ") for line in lines), lines
    assert [(r.pair_id, r.run) for r in report.runs] == [("standin-104", 1), ("standin-104", 2)]
    assert report.runs[0] == saved.runs[0] and report.label == "smoke"
    assert report.llm_calls == 5 and report.usage is not None and report.usage.calls == 5
    assert report.elapsed_seconds >= saved.elapsed_seconds
    on_disk = GoldenReport.model_validate_json(checkpoint.read_text(encoding="utf-8"))
    assert on_disk == report and not checkpoint.with_name("report.json.partial").exists()
    # nothing left: no model call, no indexing
    again = run_golden(
        golden_set, ROOT, settings, FakeLLMClient([]), 2, "smoke", tmp_path / "runs",
        resume=report,
    )  # fmt: skip
    assert again.runs == report.runs


def test_resuming_runs_again_what_failed_on_a_model_call_and_refuses_another_config(
    tmp_path: Path,
) -> None:
    """A run that failed on a model call (the fake ran out of replies, as a lost connection
    would) is made again on resume; a run that failed on a bug of ours is kept. A report never
    continues under another configuration."""
    from ticket2test.eval.golden import _retry, run_golden
    from ticket2test.llm.fake import FakeLLMClient

    from .test_eval_harness import _DRAFT, ROOT, _draft_reply

    golden_set, settings, one_run = _golden_smoke(tmp_path)
    first = run_golden(
        golden_set, ROOT, settings, FakeLLMClient([_draft_reply(_DRAFT), *one_run]), 2, "smoke",
        tmp_path / "runs",
    )  # fmt: skip
    assert [r.result.status for r in first.runs] == ["generated", "failed"]
    assert _retry(first.runs[1]) and not _retry(first.runs[0])
    bug = first.runs[1].model_copy(deep=True)
    bug.result.error = "unexpected KeyError: 'x'"
    assert not _retry(bug)

    report = run_golden(
        golden_set, ROOT, settings, FakeLLMClient(one_run), 2, "smoke", tmp_path / "runs",
        resume=first,
    )  # fmt: skip
    assert [r.result.status for r in report.runs] == ["generated", "generated"]

    changed = settings.model_copy(
        update={"context": settings.context.model_copy(update={"max_tokens": 8000})}
    )
    with pytest.raises(ValueError, match=r"configuration changed.*context\.max_tokens"):
        run_golden(
            golden_set, ROOT, changed, FakeLLMClient([]), 2, "smoke", tmp_path / "runs",
            resume=first,
        )  # fmt: skip
    other = golden_set.model_copy(update={"name": "another-set"})
    with pytest.raises(ValueError, match="not resumed"):
        run_golden(
            other, ROOT, settings, FakeLLMClient([]), 2, "smoke", tmp_path / "runs", resume=first
        )
