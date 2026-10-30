"""Draft generation with the fake LLM: ok path, insufficient-info path, retries, scrubbing."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import FIXTURES, github_raw
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.draft import generate_drafts, render_markdown
from ticket2test.draft.generator import draft_schema, precheck_missing, ticket_prompt_json
from ticket2test.llm import FakeLLMClient
from ticket2test.llm.structured import StructuredOutputError
from ticket2test.models import DraftResult, Ticket
from ticket2test.models.draft import TestCaseDraft
from ticket2test.normalize import normalize

SETTINGS = Settings.model_validate({"draft": {"skeleton": "never"}})  # the normal path


def _ticket(**changes: Any) -> Ticket:
    return normalize(github_raw(1482)).model_copy(update=changes)


def _item(**changes: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "primary",
        "intent": "Uploading a non-ASCII text file sends a correct Content-Length.",
        "markers": {"priority": "p1", "component": "multipart file upload", "suite": "regression"},
        "test_kind": "api",
        "deployment_type": "both",
        "preconditions": ["A test server that accepts uploads"],
        "steps": ["Post a file whose content is the string 'é' via the files parameter"],
        "expected_outcome": "The request succeeds and no protocol error is raised.",
        "variants": [
            {
                "name": "latin-1 char",
                "inputs": [{"name": "content", "value": "é"}],
                "expected": "request succeeds",
            }
        ],
    }
    item.update(changes)
    return item


def _reply(*items: dict[str, Any], status: str = "ok", missing: list[str] | None = None) -> str:
    return json.dumps(
        {
            "status": status,
            "missing_info": missing or [],
            "reason": "Based on the reproduction snippet.",
            "drafts": list(items),
        }
    )


def _run(
    fake: FakeLLMClient, ticket: Ticket | None = None, settings: Settings = SETTINGS
) -> DraftResult:
    return generate_drafts(ticket or _ticket(), fake, settings, provider="fake", model="fake-model")


def test_ok_path_builds_traceable_drafts() -> None:
    edge = _item(kind="edge_case", intent="Multi-byte characters")
    fake = FakeLLMClient([_reply(edge, _item())])  # primary deliberately second
    result = _run(fake)

    assert result.status == "ok"
    assert result.attempts == 1
    assert result.prompt_version == "draft_v4"
    assert (result.provider, result.model) == ("fake", "fake-model")
    assert [d.kind for d in result.drafts] == ["primary", "edge_case"]  # primary first
    assert [d.id for d in result.drafts] == ["encode/httpx#1482/d1", "encode/httpx#1482/d2"]
    first = result.drafts[0]
    assert first.ticket_id == "encode/httpx#1482"
    assert first.prompt_version == "draft_v4"
    assert first.markers.priority == "p1"
    assert first.test_kind == "api"
    assert first.deployment_type == "both"


def test_request_carries_schema_prompt_and_allowed_values() -> None:
    fake = FakeLLMClient([_reply(_item())])
    _run(fake)
    request = fake.requests[0]
    assert request.messages[0].role == "system"
    user = request.messages[1].content
    assert "Allowed priorities (highest first): p0, p1, p2, p3" in user
    assert "Allowed suites: smoke, regression, unknown" in user
    assert "Too much data for declared Content-Length" in user
    assert request.temperature == 0.0
    assert request.model == "claude-sonnet-5-5"  # drafting keeps the main model
    markers = request.json_schema["properties"]["drafts"]["items"]["properties"]["markers"]  # type: ignore[index]
    assert markers["properties"]["priority"]["enum"] == ["p0", "p1", "p2", "p3"]
    assert markers["properties"]["suite"]["enum"] == ["smoke", "regression", "unknown"]


@pytest.mark.parametrize("component", ["unknown", "Unknown", "", "n/a"])
def test_unknown_component(component: str) -> None:
    item = _item(markers={"priority": "p2", "component": component, "suite": "unknown"})
    result = _run(FakeLLMClient([_reply(item)]))
    draft = result.drafts[0]
    assert draft.markers.component == "unknown"
    assert draft.support is not None and not draft.support.component_from_ticket
    assert result.status == "ok"  # never insufficient_info for that alone


def test_support_is_checked_in_code() -> None:
    ticket = _ticket(steps_to_reproduce=["Post a file"], expected="", actual="It fails")
    item = _item(
        markers={"priority": "p1", "component": "multipart upload", "suite": "regression"},
        steps=["Post a file of 4096 bytes via the files parameter"],
    )
    support = _run(FakeLLMClient([_reply(item)]), ticket).drafts[0].support
    assert support is not None
    assert (support.explicit_steps, support.explicit_expected, support.explicit_actual) == (
        True,
        False,
        True,
    )
    assert support.invented_numbers == ["4096"]  # not in the ticket
    assert 0.0 < support.grounding < 1.0 and support.ungrounded_words


def test_a_self_rating_is_no_longer_accepted() -> None:
    fake = FakeLLMClient([_reply(_item(confidence=0.9)), _reply(_item())])
    result = _run(fake)
    assert result.attempts == 2 and "confidence" not in result.drafts[0].model_dump()


def test_old_drafts_with_a_self_rating_still_load() -> None:
    draft = _run(FakeLLMClient([_reply(_item())])).drafts[0]
    legacy = {**draft.model_dump(), "confidence": 0.9}
    assert TestCaseDraft.model_validate(legacy) == draft


def test_insufficient_info_from_llm() -> None:
    reply = _reply(status="insufficient_info", missing=["steps_to_reproduce", "expected_behavior"])
    result = _run(FakeLLMClient([reply]))
    assert result.status == "insufficient_info"
    assert result.missing_info == ["steps_to_reproduce", "expected_behavior"]
    assert result.drafts == []


def test_precheck_skips_llm_for_empty_ticket() -> None:
    ticket = _ticket(description=None, steps_to_reproduce=[], expected=None)
    fake = FakeLLMClient([])
    result = _run(fake, ticket)
    assert result.status == "insufficient_info"
    assert result.missing_info == ["steps_to_reproduce", "expected_behavior"]
    assert result.attempts == 0
    assert fake.requests == []


def test_precheck_leaves_tickets_with_a_description_to_the_llm() -> None:
    assert precheck_missing(_ticket()) == []
    assert precheck_missing(_ticket(description=None, steps_to_reproduce=["x"], expected=None)) == [
        "expected_behavior"
    ]


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        _reply(_item(markers={"priority": "urgent", "component": "c", "suite": "smoke"})),
        _reply(_item(markers={"priority": "p1", "component": "c", "suite": "nightly"})),
        _reply(_item(kind="edge_case")),  # no primary
        _reply(_item(), *[_item(kind="edge_case")] * 4),  # too many edge cases
        _reply(_item(test_kind="browser")),
        _reply(_item(), status="insufficient_info", missing=["steps_to_reproduce"]),
        _reply(status="insufficient_info"),  # no missing_info
    ],
)
def test_invalid_output_is_retried_then_accepted(bad: str) -> None:
    fake = FakeLLMClient([bad, _reply(_item())])
    result = _run(fake)
    assert result.status == "ok"
    assert result.attempts == 2


def test_malformed_output_fails_cleanly_after_retries() -> None:
    fake = FakeLLMClient(["{broken"] * 10)
    with pytest.raises(StructuredOutputError):
        _run(fake)
    assert len(fake.requests) == SETTINGS.llm.max_retries_on_bad_json + 1


def test_secrets_are_scrubbed_from_prompt_and_output() -> None:
    secret = "ghp_" + "Z9y8" * 9
    ticket = _ticket(description=f"Use token {secret} to reproduce.")
    leaky = _item(steps=[f"Authenticate with {secret}"])
    fake = FakeLLMClient([_reply(leaky)])
    result = _run(fake, ticket)
    assert secret not in fake.requests[0].messages[1].content
    assert secret not in result.model_dump_json()
    assert "[REDACTED:github_token]" in result.drafts[0].steps[0]
    assert result.redactions == 2


def test_comment_budget_in_prompt() -> None:
    ticket = normalize(github_raw(914))
    payload = json.loads(ticket_prompt_json(ticket, max_comment_chars=500))
    assert sum(len(c["body"]) for c in payload["comments"]) <= 500
    assert payload["comments_not_shown"] == 43 - len(payload["comments"])


def test_draft_schema_does_not_mutate_between_calls() -> None:
    first = draft_schema(["A"], ["s1"])
    second = draft_schema(["B"], ["s2"])
    assert first != second
    assert copy.deepcopy(second) == draft_schema(["B"], ["s2"])


# --- Markdown -------------------------------------------------------------------------------


def test_markdown_ok() -> None:
    edge = _item(
        kind="edge_case", markers={"priority": "p2", "component": "unknown", "suite": "smoke"}
    )
    result = _run(FakeLLMClient([_reply(_item(), edge)]))
    md = render_markdown(result, _ticket())
    assert md.startswith("# Test drafts for encode/httpx#1482:")
    assert "## 1. Main test:" in md and "## 2. Edge case:" in md
    assert "| Priority | p1 |" in md
    assert "| Test type | API |" in md
    assert "| Runs on | All deployments |" in md
    assert "| Ticket has explicit steps to reproduce |" in md and "Confidence" not in md
    assert "unknown (could not tell from the ticket)" in md
    assert "**Steps**" in md and "**Expected result:**" in md
    assert "| latin-1 char | content = é | request succeeds |" in md


def test_markdown_insufficient_info() -> None:
    reply = _reply(status="insufficient_info", missing=["expected_behavior"])
    md = render_markdown(_run(FakeLLMClient([reply])), _ticket())
    assert "## Needs more information" in md
    assert "What should happen instead (expected behavior)" in md


# --- CLI -------------------------------------------------------------------------------------


def test_cli_draft_writes_json_and_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticket_file = tmp_path / "ticket.json"
    ticket_file.write_text(_ticket().model_dump_json(), encoding="utf-8")
    fake = FakeLLMClient([_reply(_item())])
    monkeypatch.setattr("ticket2test.llm.factory.create_llm_client", lambda *a, **k: fake)

    result = CliRunner().invoke(app, ["draft", str(ticket_file), "--out", str(tmp_path / "d")])
    assert result.exit_code == 0, result.output
    assert "1 draft(s)" in result.output
    stored = DraftResult.model_validate_json(
        (tmp_path / "d" / "encode_httpx_1482.drafts.json").read_text(encoding="utf-8")
    )
    assert stored.provider == "claude_code_cli"
    assert (tmp_path / "d" / "encode_httpx_1482.drafts.md").is_file()


def test_cli_draft_reports_llm_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticket_file = tmp_path / "ticket.json"
    ticket_file.write_text(_ticket().model_dump_json(), encoding="utf-8")
    fake = FakeLLMClient(["nope"] * 5)
    monkeypatch.setattr("ticket2test.llm.factory.create_llm_client", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["draft", str(ticket_file)])
    assert result.exit_code == 1
    assert "failed validation" in result.output


def test_cli_draft_bad_ticket_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(app, ["draft", str(bad)])
    assert result.exit_code == 2


def test_vague_fixture_is_a_valid_ticket() -> None:
    ticket = Ticket.model_validate_json(
        (FIXTURES / "tickets" / "vague_ticket.json").read_text(encoding="utf-8")
    )
    assert precheck_missing(ticket) == []  # has a description, so the LLM decides


def test_the_draft_picks_a_component_from_the_suites_list() -> None:
    """Found in the first real trial: the draft invented a component the suite doesn't have,
    so the template step's "same component first" matched nothing."""
    settings = SETTINGS.model_copy(
        update={
            "markers": SETTINGS.markers.model_copy(update={"components": ["multipart", "auth"]})
        }
    )
    markers = {"priority": "p1", "suite": "regression"}
    fake = FakeLLMClient(
        [
            _reply(_item(markers={**markers, "component": "Multipart"})),
            _reply(_item(markers={**markers, "component": "file uploads"})),
        ]
    )
    first = _run(fake, settings=settings)
    assert first.drafts[0].markers.component == "multipart"  # the suite's spelling
    assert "Allowed components: multipart, auth, unknown" in fake.requests[0].messages[-1].content
    second = _run(fake, settings=settings)
    assert second.drafts[0].markers.component == "unknown"  # never an invented name
