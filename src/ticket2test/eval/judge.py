"""LLM-as-judge: is a draft faithful to its ticket? UNVALIDATED until checked against humans.

Off by default (it costs one LLM call per ticket). Reports keep judge results in their own
section, apart from the measured metrics.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import Settings
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.masking import masker_of, unmask_model
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.draft import DraftResult
from ticket2test.models.ticket import Ticket
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub_text

JUDGE_PROMPT = "judge_draft_v1"
_MAX_CHARS = 12000


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal["faithful", "partly", "unfaithful"]
    score: float = Field(ge=0.0, le=1.0)
    unsupported: list[str]
    missing: list[str]
    reason: str


def judge_draft(
    ticket: Ticket, drafts: DraftResult, client: LLMClient, settings: Settings
) -> tuple[JudgeVerdict, int]:
    prompt = load_prompt(JUDGE_PROMPT, settings.paths.prompts_dir)
    ticket_json = ticket.model_dump_json(
        indent=1, include={"title", "description", "steps_to_reproduce", "expected", "actual"}
    )
    drafts_json = drafts.model_dump_json(indent=1, include={"status", "missing_info", "drafts"})
    user = prompt.render_user(
        ticket_json=scrub_text(ticket_json[:_MAX_CHARS]),
        drafts_json=scrub_text(drafts_json[:_MAX_CHARS]),
    )
    request = LLMRequest(
        messages=(
            Message(role="system", content=prompt.system),
            Message(role="user", content=user),
        ),
        temperature=settings.llm.temperature,
        seed=settings.llm.seed,
        max_output_tokens=min(settings.llm.max_output_tokens, 2000),
        json_schema=strict_schema(JudgeVerdict),
        model=model_name(settings, "draft"),
    )
    result = complete_structured(
        client, request, JudgeVerdict, max_retries=settings.llm.max_retries_on_bad_json
    )
    return unmask_model(result.value, masker_of(client)), result.attempts
