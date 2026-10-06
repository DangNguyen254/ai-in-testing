"""The two LLM steps of retrieval: query rewrite and follow-up search requests."""

from __future__ import annotations

from ticket2test.config import LLMStep, Settings
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import StructuredResult, complete_structured
from ticket2test.models.retrieval import FollowupRequest, QueryRewrite
from ticket2test.prompts import PromptTemplate
from ticket2test.security import scrub_text


def _request(
    prompt: PromptTemplate,
    user: str,
    settings: Settings,
    schema: dict[str, object],
    step: LLMStep,
) -> LLMRequest:
    return LLMRequest(
        messages=(
            Message(role="system", content=prompt.system),
            Message(role="user", content=user),
        ),
        temperature=settings.llm.temperature,
        seed=settings.llm.seed,
        max_output_tokens=min(settings.llm.max_output_tokens, 4000),
        json_schema=schema,
        model=model_name(settings, step),
    )


def rewrite_query(
    client: LLMClient, prompt: PromptTemplate, ticket_text: str, settings: Settings
) -> StructuredResult[QueryRewrite]:
    user = prompt.render_user(ticket_text=scrub_text(ticket_text))
    return complete_structured(
        client,
        _request(prompt, user, settings, strict_schema(QueryRewrite), "query_rewrite"),
        QueryRewrite,
        max_retries=settings.llm.max_retries_on_bad_json,
    )


def request_followups(
    client: LLMClient,
    prompt: PromptTemplate,
    ticket_text: str,
    previous_searches: list[str],
    results: list[str],
    settings: Settings,
) -> StructuredResult[FollowupRequest]:
    user = prompt.render_user(
        ticket_text=scrub_text(ticket_text),
        previous_searches="\n".join(previous_searches) or "(none)",
        results=scrub_text("\n".join(results)) or "(no results)",
        max_searches=str(settings.retrieval.followup_max_searches),
    )
    return complete_structured(
        client,
        _request(prompt, user, settings, strict_schema(FollowupRequest), "retrieval_followup"),
        FollowupRequest,
        max_retries=settings.llm.max_retries_on_bad_json,
    )
