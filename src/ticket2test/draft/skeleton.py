"""A partial draft skeleton for a ticket too vague to draft (one extra LLM call, only then).

The normal output for such a ticket is ``insufficient_info`` with the missing items. The
skeleton adds what the ticket does support, with every unknown left as a numbered question
(``[Q1]``) for the reporter. The model rejects a skeleton that refers to a missing question,
leaves a question unused, or contains a number the ticket doesn't have, and the LLM is asked to
fix it (capped retries). It is never used for generation.
"""

from __future__ import annotations

from ticket2test.config import Settings
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.masking import masker_of, unmask_model
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.draft import CTX_TICKET_TEXT, DraftResult, DraftSkeleton
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub


def add_skeleton(
    result: DraftResult, ticket_json: str, client: LLMClient, settings: Settings
) -> DraftResult:
    """``result`` with a skeleton attached (and its LLM calls counted)."""
    prompt = load_prompt(settings.draft.skeleton_prompt, settings.paths.prompts_dir)
    ticket_scrub = scrub(ticket_json)
    user = prompt.render_user(
        missing=", ".join(result.missing_info) or "none (the draft was judged sufficient)",
        reason=result.reason or "none given",
        ticket_json=ticket_scrub.text,
    )
    request = LLMRequest(
        messages=(
            Message(role="system", content=prompt.system),
            Message(role="user", content=user),
        ),
        temperature=settings.llm.temperature,
        seed=settings.llm.seed,
        max_output_tokens=min(settings.llm.max_output_tokens, 4000),
        json_schema=strict_schema(DraftSkeleton),
        model=model_name(settings, "draft"),
    )
    context = {CTX_TICKET_TEXT: ticket_scrub.text}
    found = complete_structured(
        client, request, DraftSkeleton, settings.llm.max_retries_on_bad_json, context
    )
    skeleton = unmask_model(found.value, masker_of(client), context)
    return result.model_copy(
        update={
            "skeleton": skeleton,
            "skeleton_prompt_version": prompt.version,
            "attempts": result.attempts + found.attempts,
            "redactions": result.redactions + ticket_scrub.redacted,
        }
    )
