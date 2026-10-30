"""Ticket -> DraftResult (structured test-case drafts) via the configured LLM."""

from __future__ import annotations

import json
from typing import Any

from ticket2test.config import Settings
from ticket2test.draft.support import support_for
from ticket2test.knowledge.vocabulary import draft_vocabulary
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.masking import masker_of, unmask_model
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.draft import (
    CTX_PRIORITIES,
    CTX_SUITES,
    UNKNOWN,
    DraftItem,
    DraftResponse,
    DraftResult,
    MissingInfo,
    TestCaseDraft,
)
from ticket2test.models.ticket import Ticket
from ticket2test.prompts import PromptTemplate, load_prompt
from ticket2test.security import scrub

_UNKNOWN_SPELLINGS = {"", "unknown", "n/a", "na", "none", "unclear", "?"}


def generate_drafts(
    ticket: Ticket,
    client: LLMClient,
    settings: Settings,
    provider: str,
    model: str,
    prompt: PromptTemplate | None = None,
) -> DraftResult:
    prompt = prompt or load_prompt(settings.draft.prompt_version, settings.paths.prompts_dir)
    base: dict[str, Any] = {
        "ticket_id": ticket.id,
        "prompt_version": prompt.version,
        "provider": provider,
        "model": model,
    }

    missing = precheck_missing(ticket)
    if missing:
        return DraftResult(
            status="insufficient_info",
            missing_info=missing,
            reason="The ticket has no description, steps, or expected behavior to work from.",
            attempts=0,
            **base,
        )

    ticket_scrub = scrub(ticket_prompt_json(ticket, settings.draft.max_comment_chars))
    markers = settings.markers
    values = {
        "ticket_json": ticket_scrub.text,
        "priorities": ", ".join(markers.priorities),
        "suites": ", ".join([*markers.suites, UNKNOWN]),
    }
    vocabulary = draft_vocabulary(ticket, settings)
    # the suite's list, else the component markers of the glossary terms the ticket names
    components = list(markers.components) or vocabulary.components
    if "{{components}}" in prompt.user:  # from draft_v3 on
        values["components"] = ", ".join([*components, UNKNOWN]) if components else "(not given)"
    if "{{vocabulary}}" in prompt.user:  # from draft_v4 on
        values["vocabulary"] = scrub(vocabulary.text).text if vocabulary.text else "(none)"
    user = prompt.render_user(**values)
    request = LLMRequest(
        messages=(
            Message(role="system", content=prompt.system),
            Message(role="user", content=user),
        ),
        temperature=settings.llm.temperature,
        seed=settings.llm.seed,
        max_output_tokens=settings.llm.max_output_tokens,
        json_schema=draft_schema(markers.priorities, markers.suites, components),
        model=model_name(settings, "draft"),
    )
    result = complete_structured(
        client,
        request,
        DraftResponse,
        max_retries=settings.llm.max_retries_on_bad_json,
        context={CTX_PRIORITIES: markers.priorities, CTX_SUITES: markers.suites},
    )

    restored = unmask_model(
        result.value,
        masker_of(client),
        {CTX_PRIORITIES: markers.priorities, CTX_SUITES: markers.suites},
    )
    response, output_redactions = _scrub_output(restored)
    drafts = [
        _to_stored(item, ticket, index, prompt.version, components)
        for index, item in enumerate(_primary_first(response.drafts), start=1)
    ]
    drafted = DraftResult(
        status=response.status,
        missing_info=response.missing_info,
        reason=response.reason,
        drafts=drafts,
        attempts=result.attempts,
        redactions=ticket_scrub.redacted + output_redactions,
        **base,
    )
    mode = settings.draft.skeleton
    unclear = not ticket.steps_to_reproduce or not (ticket.expected or "").strip()
    vague = drafted.status == "insufficient_info" or unclear  # checked in code, no score
    if mode == "always" or (mode == "auto" and vague):
        from ticket2test.draft.skeleton import add_skeleton

        drafted = add_skeleton(
            drafted, ticket_prompt_json(ticket, settings.draft.max_comment_chars), client, settings
        )
    return drafted


def precheck_missing(ticket: Ticket) -> list[MissingInfo]:
    """Deterministic insufficient-info check for tickets with nothing to work from.

    Only fires when there is no description at all: then steps and expected behavior can only
    come from the extracted fields. Everything subtler is the LLM's call.
    """
    if ticket.description:
        return []
    missing: list[MissingInfo] = []
    if not ticket.steps_to_reproduce:
        missing.append("steps_to_reproduce")
    if not ticket.expected:
        missing.append("expected_behavior")
    return missing


def ticket_prompt_json(ticket: Ticket, max_comment_chars: int) -> str:
    """The ticket fields the LLM sees. Comments are included in order up to a character budget."""
    comments: list[dict[str, str]] = []
    used = 0
    for comment in ticket.comments:
        if used + len(comment.body) > max_comment_chars:
            break
        comments.append({"author": comment.author or "unknown", "body": comment.body})
        used += len(comment.body)
    payload: dict[str, Any] = {
        "id": ticket.id,
        "title": ticket.title,
        "labels": ticket.labels,
        "components": ticket.components,
        "description": ticket.description,
        "steps_to_reproduce": ticket.steps_to_reproduce,
        "expected": ticket.expected,
        "actual": ticket.actual,
        "comments": comments,
        "comments_not_shown": len(ticket.comments) - len(comments) + ticket.comments_omitted,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def draft_schema(
    priorities: list[str], suites: list[str], components: list[str] | None = None
) -> dict[str, Any]:
    """Wire schema for DraftResponse, with the configured marker values as enums (components
    only when the suite's list is configured)."""
    schema = strict_schema(DraftResponse)
    markers = schema["properties"]["drafts"]["items"]["properties"]["markers"]["properties"]
    markers["priority"]["enum"] = list(priorities)
    markers["suite"]["enum"] = [*suites, UNKNOWN]
    if components:
        markers["component"]["enum"] = [*components, UNKNOWN]
    return schema


def known_component(value: str, components: list[str]) -> str:
    """The draft's component as one of the suite's values: the same spelling ignoring case,
    else "unknown" (never an invented name). Without a configured list, as given."""
    if value.lower() in _UNKNOWN_SPELLINGS:
        return UNKNOWN
    if not components:
        return value
    return next((c for c in components if c.lower() == value.lower()), UNKNOWN)


def _primary_first(items: list[DraftItem]) -> list[DraftItem]:
    return sorted(items, key=lambda item: item.kind != "primary")


def _to_stored(
    item: DraftItem,
    ticket: Ticket,
    index: int,
    prompt_version: str,
    components: list[str] | None = None,
) -> TestCaseDraft:
    component = known_component(item.markers.component.strip(), components or [])
    data = item.model_dump()
    data["markers"]["component"] = component
    texts = [
        *item.preconditions,
        *item.steps,
        item.expected_outcome,
        *(f"{v.name} {v.expected} " + " ".join(i.value for i in v.inputs) for v in item.variants),
    ]
    return TestCaseDraft(
        id=f"{ticket.id}/d{index}",
        ticket_id=ticket.id,
        prompt_version=prompt_version,
        support=support_for(ticket, "" if component == UNKNOWN else component, texts),
        **data,
    )


def _scrub_output(response: DraftResponse) -> tuple[DraftResponse, int]:
    """Run the secret scrubber over every string the LLM produced."""
    total = 0

    def walk(value: Any) -> Any:
        nonlocal total
        if isinstance(value, str):
            result = scrub(value)
            total += result.redacted
            return result.text
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value

    cleaned = walk(response.model_dump())
    return (DraftResponse.model_validate(cleaned) if total else response), total
