"""Repair loop (Phase 7) with the fake LLM: validator errors go back, capped by config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ticket2test.index.indexer import IndexData
from ticket2test.llm.fake import FakeLLMClient
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.validate.repair import generate_with_repair

from .test_generate import CONVENTIONS, GOOD_CODE, _draft, _reply, _settings
from .test_generate import index as index
from .test_generate import retrieval as retrieval

# The page object has no ``rule_count``: an invented name the validators catch.
BAD_CODE = GOOD_CODE.replace(
    "self.check.assertEqual(0, rules.total_count)", "self.check.assertEqual(0, rules.rule_count)"
)


def _run(
    index: IndexData,
    retrieval: RetrievalResult,
    tmp_path: Path,
    replies: list[str],
    draft: TestCaseDraft | None = None,
    **settings: Any,
) -> tuple[Any, FakeLLMClient]:
    base = _settings(tmp_path)
    config = base.model_copy(
        update={"repair": base.repair.model_copy(update=settings)} if settings else {}
    )
    fake = FakeLLMClient(replies)
    result = generate_with_repair(
        draft or _draft(), retrieval, index, config, fake, "fake", "fake-model", CONVENTIONS
    )
    return result, fake


def test_bad_code_is_caught_and_repaired(
    index: IndexData,
    retrieval: RetrievalResult,
    tmp_path: Path,
) -> None:
    assert "rule_count" in BAD_CODE
    result, fake = _run(index, retrieval, tmp_path, [_reply(BAD_CODE), _reply()])

    assert result.report.ok and result.report.repairs == 1 and result.llm_calls == 2
    assert result.generated.attempts == 2
    assert "rules.total_count" in result.generated.code
    # The history records what was sent, and the report is stored on the test.
    assert any("no member 'rule_count'" in e for e in result.report.history[0])
    stored = result.generated.validation_report
    assert stored is not None and stored["repairs"] == 1 and stored["findings"] == []

    # The repair continues the conversation: the bad reply, then the errors.
    repair_request = fake.requests[1]
    roles = [m.role for m in repair_request.messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert repair_request.messages[2].content == _reply(BAD_CODE)
    turn = repair_request.messages[3].content
    assert "Validator errors:" in turn and "no member 'rule_count'" in turn


def test_repair_stops_at_the_configured_cap(
    index: IndexData,
    retrieval: RetrievalResult,
    tmp_path: Path,
) -> None:
    result, fake = _run(index, retrieval, tmp_path, [_reply(BAD_CODE)] * 10, max_attempts=3)
    assert not result.report.ok
    assert result.report.repairs == 3 and len(result.report.history) == 3
    assert len(fake.requests) == 4  # 1 generation + exactly 3 repairs
    assert fake.remaining == 6


@pytest.mark.parametrize("cap", [0, 1])
def test_small_caps(
    index: IndexData,
    retrieval: RetrievalResult,
    tmp_path: Path,
    cap: int,
) -> None:
    result, fake = _run(index, retrieval, tmp_path, [_reply(BAD_CODE)] * 5, max_attempts=cap)
    assert len(fake.requests) == 1 + cap and result.report.repairs == cap


def test_a_good_first_reply_needs_no_repair(
    index: IndexData,
    retrieval: RetrievalResult,
    tmp_path: Path,
) -> None:
    result, fake = _run(index, retrieval, tmp_path, [_reply()])
    assert result.report.ok and result.report.repairs == 0 and len(fake.requests) == 1


def test_warnings_outside_the_repair_checks_never_trigger_a_repair(
    index: IndexData,
    retrieval: RetrievalResult,
    tmp_path: Path,
) -> None:
    draft = _draft(expected_outcome="An audit entry is written for the delete.")
    result, fake = _run(
        index, retrieval, tmp_path, [_reply(), _reply()], draft=draft, warning_checks=[]
    )
    assert result.report.ok and result.report.warnings and len(fake.requests) == 1


def test_an_unusable_repair_reply_keeps_the_last_version(
    index: IndexData,
    retrieval: RetrievalResult,
    tmp_path: Path,
) -> None:
    # Generation is bad; every repair reply is invalid JSON (3 tries: 1 + 2 retries).
    result, fake = _run(index, retrieval, tmp_path, [_reply(BAD_CODE), "{", "{", "{"])
    assert not result.report.ok and result.report.repairs == 1
    assert "rules.rule_count" in result.generated.code
    assert result.llm_calls == 4 and len(fake.requests) == 4


def test_an_outcome_no_check_covers_gets_one_repair_round(
    index: IndexData,
    retrieval: RetrievalResult,
    tmp_path: Path,
) -> None:
    """Found in the real trial: "page content still delivered" was never checked, and as a
    warning it never reached a repair round. Warnings of ``repair.warning_checks`` start one
    round (``max_warning_rounds``); a round that brings errors back is undone."""
    draft = _draft(expected_outcome="An audit entry is written for the delete.")
    result, fake = _run(index, retrieval, tmp_path, [_reply(), _reply(), _reply()], draft)
    assert result.report.ok and result.llm_calls == 2 and result.report.repairs == 1
    turn = fake.requests[1].messages[-1].content
    assert "Findings to address" in turn and "audit entry" in turn
    assert "Validator errors:\n(none)" in turn
    # off: no round for warnings
    result, fake = _run(index, retrieval, tmp_path, [_reply()], draft, warning_checks=[])
    assert result.llm_calls == 1 and result.report.repairs == 0
    # the round breaks the test: the version before it is kept
    result, fake = _run(index, retrieval, tmp_path, [_reply(), _reply(BAD_CODE)], draft)
    assert result.report.ok and "rules.total_count" in result.generated.code
    assert result.llm_calls == 2
