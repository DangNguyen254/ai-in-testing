"""Live draft generation with the configured provider. Run with `pytest -m live`.

Uses `llm.provider` from config (default: claude_code_cli, i.e. your Claude Code login).
Each test makes one or more real LLM calls.
"""

from __future__ import annotations

import pytest

from tests.conftest import FIXTURES, GITHUB_FIXTURE_ISSUES, REPO_ROOT, github_raw
from ticket2test.config import load_settings
from ticket2test.draft import generate_drafts
from ticket2test.llm.factory import create_llm_client, model_name
from ticket2test.models import DraftResult, Ticket
from ticket2test.normalize import normalize


def _draft(ticket: Ticket) -> DraftResult:
    settings = load_settings(REPO_ROOT / "config.yaml")
    client = create_llm_client(settings)
    return generate_drafts(
        ticket, client, settings, provider=settings.llm.provider, model=model_name(settings)
    )


@pytest.mark.live
@pytest.mark.parametrize("number", GITHUB_FIXTURE_ISSUES)
def test_fixture_ticket_end_to_end(number: int) -> None:
    result = _draft(normalize(github_raw(number)))
    assert result.status in ("ok", "insufficient_info")
    if result.status == "ok":
        assert result.drafts[0].kind == "primary"
        assert 1 <= len(result.drafts) <= 4
        assert all(d.prompt_version == "draft_v1" for d in result.drafts)
    else:
        assert result.missing_info


@pytest.mark.live
def test_vague_ticket_returns_insufficient_info() -> None:
    ticket = Ticket.model_validate_json(
        (FIXTURES / "tickets" / "vague_ticket.json").read_text(encoding="utf-8")
    )
    result = _draft(ticket)
    assert result.status == "insufficient_info"
    assert result.missing_info
