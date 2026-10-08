"""Partial draft skeletons for vague tickets (fake LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.config import Settings
from ticket2test.draft import generate_drafts
from ticket2test.draft.render import render_markdown
from ticket2test.llm.fake import FakeLLMClient
from ticket2test.models.ticket import Ticket
from ticket2test.normalize import normalize

EXPORT = REPO_ROOT / "tests" / "fixtures" / "jira" / "vague_oom.json"

INSUFFICIENT = json.dumps(
    {
        "status": "insufficient_info",
        "missing_info": ["steps_to_reproduce", "expected_behavior"],
        "reason": "Only a reproduction hint and a suspected cause; no expected behavior.",
        "drafts": [],
    }
)


def _skeleton(**overrides: Any) -> str:
    body: dict[str, Any] = {
        "intent": "The report export service stays up under long content.",
        "test_kind": "unknown",
        "preconditions": ["The report export service is running [Q2]."],
        "steps": [
            "Run long_content_load.py with long content (~7K words) and [Q3] clients.",
        ],
        "expected_outcome": "The service does not run out of memory; [Q1].",
        "open_questions": [
            {"id": "Q1", "question": "What should happen past the client limit?", "why": "pass"},
            {"id": "Q2", "question": "Which environment?", "why": "where to run"},
            {"id": "Q3", "question": "How many clients at once?", "why": "the load"},
        ],
        "notes": "This reads like a load test.",
    }
    body.update(overrides)
    return json.dumps(body)


@pytest.fixture
def ticket() -> Ticket:
    return normalize(JiraExportSource(EXPORT).fetch("STND-901"))


def _settings(mode: str = "auto") -> Settings:
    return Settings.model_validate({"draft": {"skeleton": mode}})


def _run(ticket: Ticket, replies: list[str], mode: str = "auto") -> Any:
    fake = FakeLLMClient(replies)
    result = generate_drafts(ticket, fake, _settings(mode), provider="fake", model="m")
    return result, fake


def test_an_insufficient_ticket_gets_a_skeleton(ticket: Ticket) -> None:
    result, _fake = _run(ticket, [INSUFFICIENT, _skeleton()])
    assert result.status == "insufficient_info" and not result.drafts
    assert result.skeleton is not None and result.attempts == 2
    assert [q.id for q in result.skeleton.open_questions] == ["Q1", "Q2", "Q3"]
    assert result.skeleton_prompt_version == "skeleton_v1"
    markdown = render_markdown(result, ticket)
    assert "## Needs more information" in markdown
    assert "## Partial draft (for discussion, not generated)" in markdown
    assert "| Q3 | How many clients at once? | the load |" in markdown


def test_an_invented_number_is_sent_back(ticket: Ticket) -> None:
    invented = _skeleton(
        steps=["Run long_content_load.py with long content (~7K words) and 500 clients [Q3]."]
    )
    result, fake = _run(ticket, [INSUFFICIENT, invented, _skeleton()])
    assert result.attempts == 3
    assert "numbers ['500'] are not in the ticket" in fake.requests[2].messages[-1].content


def test_every_question_is_referenced_and_every_reference_exists(ticket: Ticket) -> None:
    unused = _skeleton(expected_outcome="The service does not run out of memory.")
    dangling = _skeleton(steps=["Run long_content_load.py [Q3] [Q9]."])
    result, fake = _run(ticket, [INSUFFICIENT, unused, dangling, _skeleton()])
    assert result.skeleton is not None and result.attempts == 4
    assert "never referenced" in fake.requests[2].messages[-1].content
    assert "don't exist: ['Q9']" in fake.requests[3].messages[-1].content


def test_modes(ticket: Ticket) -> None:
    result, fake = _run(ticket, [INSUFFICIENT], mode="never")
    assert result.skeleton is None and len(fake.requests) == 1
    empty = ticket.model_copy(update={"description": "", "steps_to_reproduce": [], "expected": ""})
    result, fake = _run(empty, [])  # decided in code: nothing to build a skeleton from
    assert result.skeleton is None and fake.requests == []


def test_written_drafts_stay_round_trippable(ticket: Ticket, tmp_path: Path) -> None:
    result, _ = _run(ticket, [INSUFFICIENT, _skeleton()])
    path = tmp_path / "d.json"
    path.write_text(result.model_dump_json(), encoding="utf-8")
    from ticket2test.models import DraftResult

    again = DraftResult.model_validate_json(path.read_text(encoding="utf-8"))
    assert again.skeleton == result.skeleton
