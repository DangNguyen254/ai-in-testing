"""The step plan: one LLM call before generation that maps each draft step to a member.

The generator repeats its template's steps, and a member that is only listed in the context
(the member cards) is not picked up. So the choice is made a task of its own: the draft's
lines (preconditions, steps, expected outcome; labels S1, S2, ...) and the member cards
(labels M1, M2, ...) go to the model (prompt ``step_plan_v1``, the generate step's model),
and it answers with labels only. Code checks them: a step or member that wasn't shown is
dropped. What is left goes into the generation context as a plan, the card next to its step.

A failed call means no plan; generation goes on as without the switch.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import Settings
from ticket2test.generate.context import Piece
from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import StructuredOutputError, complete_structured
from ticket2test.models.draft import TestCaseDraft
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub_text

_MAX_STEPS = 40
_MAX_MEMBERS = 3  # per step

TITLE = (
    "Step plan (the suite's member for each step of the draft: call it for that step, also "
    "when the template doesn't call it; steps not listed follow the template)"
)


class PlannedStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step: str  # a label shown: S1, S2, ...
    members: list[str] = Field(max_length=_MAX_MEMBERS)  # labels shown: M1, M2, ...


class StepPlanReply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: list[PlannedStep] = Field(max_length=_MAX_STEPS)


def step_plan_piece(
    draft: TestCaseDraft, cards: list[str], settings: Settings, client: LLMClient
) -> tuple[Piece | None, int]:
    """The plan as a context piece (None: no step got a member, or the call failed), and the
    LLM calls it took. ``cards``: the member cards' lines (``members.member_cards``)."""
    lines = [
        *(f"(precondition) {p}" for p in draft.preconditions),
        *draft.steps,
        f"(expected outcome) {draft.expected_outcome}",
    ][:_MAX_STEPS]
    steps = {f"S{n}": line for n, line in enumerate(lines, 1)}
    menu = {f"M{n}": card.removeprefix("- ") for n, card in enumerate(cards, 1)}
    if not menu:
        return None, 0
    prompt = load_prompt(settings.generate.step_plan_prompt, settings.paths.prompts_dir)
    user = prompt.render_user(
        intent=scrub_text(draft.intent),
        steps=scrub_text("\n".join(f"{label}. {line}" for label, line in steps.items())),
        members=scrub_text("\n".join(f"{label}: {card}" for label, card in menu.items())),
    )
    request = LLMRequest(
        messages=(
            Message(role="system", content=prompt.system),
            Message(role="user", content=user),
        ),
        temperature=settings.llm.temperature,
        seed=settings.llm.seed,
        max_output_tokens=min(settings.llm.max_output_tokens, 1500),
        json_schema=strict_schema(StepPlanReply),
        model=model_name(settings, "generate"),
    )
    try:
        result = complete_structured(
            client, request, StepPlanReply, max_retries=settings.llm.max_retries_on_bad_json
        )
    except StructuredOutputError as exc:
        return None, exc.attempts
    except LLMError:
        return None, 1
    chosen: dict[str, list[str]] = {}
    for planned in result.value.steps:  # checked by code: only labels that were shown
        label = planned.step.strip()
        if label not in steps:
            continue
        for member in planned.members:
            if member.strip() in menu and member.strip() not in chosen.setdefault(label, []):
                chosen[label].append(member.strip())
    body = [
        f"- {steps[label]}\n" + "\n".join(f"  - {menu[m]}" for m in chosen[label])
        for label in steps
        if chosen.get(label)
    ]
    return (Piece(TITLE, "\n".join(body)) if body else None), result.attempts
