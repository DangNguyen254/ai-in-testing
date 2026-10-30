"""Is the draft already covered? One LLM call before generation, checked by code.

The reuse decision's word match (``reuse.covered_min``) is strict and lexical: ticket wording
and test identifiers rarely overlap enough, so a test that does the same thing step for step
still scores far below the bar. When the area is certain and the decision is to write a new
test, the closest candidates (code and one data entry each, within the context budget) go to
the model with the draft (prompt ``coverage_v1``, step ``coverage``):

- **covered**: nothing is generated; the decision points at the test, with the model's reason;
- **partial**: generation goes on, with what the existing test lacks put into the context and
  the review checklist (the new test should add exactly that);
- **not_covered**: nothing changes.

Code checks the answer: the test must be one of the labels shown; anything else is ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import Settings
from ticket2test.generate.context import estimate_tokens
from ticket2test.generate.reuse import Candidate, ReuseDecision
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.masking import masker_of, unmask_model
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.draft import TestCaseDraft
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub_text

_MAX_MISSING = 8


class CoverageJudgement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal["covered", "partial", "not_covered"]
    test: str | None
    missing: list[str] = Field(max_length=_MAX_MISSING)
    reason: str


@dataclass(frozen=True)
class Coverage:
    verdict: Literal["covered", "partial", "not_covered"]
    candidate: Candidate | None  # the test the verdict is about (checked against the labels)
    missing: list[str]
    reason: str
    llm_calls: int


def judge_coverage(
    draft: TestCaseDraft,
    decision: ReuseDecision,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
) -> Coverage | None:
    """The model's verdict on the closest candidates; None when there is nothing to compare."""
    reuse = settings.generate.reuse
    shown = _shown(decision, index, settings)
    if not shown:
        return None
    prompt = load_prompt(reuse.coverage_prompt, settings.paths.prompts_dir)
    draft_json = draft.model_dump_json(
        indent=1,
        include={"intent", "preconditions", "steps", "expected_outcome", "variants"},
    )
    blocks = [f"## {label}: {c.test}\n\n{text}" for label, c, text in shown]
    user = prompt.render_user(
        draft=scrub_text(draft_json), candidates=scrub_text("\n\n".join(blocks))
    )
    request = LLMRequest(
        messages=(
            Message(role="system", content=prompt.system),
            Message(role="user", content=user),
        ),
        temperature=settings.llm.temperature,
        seed=settings.llm.seed,
        max_output_tokens=min(settings.llm.max_output_tokens, 1500),
        json_schema=strict_schema(CoverageJudgement),
        model=model_name(settings, "coverage"),
    )
    result = complete_structured(
        client, request, CoverageJudgement, max_retries=settings.llm.max_retries_on_bad_json
    )
    answer = unmask_model(result.value, masker_of(client))
    labels = {label: c for label, c, _ in shown}
    candidate = labels.get((answer.test or "").strip())
    verdict = answer.verdict if candidate is not None else "not_covered"  # checked by code
    return Coverage(verdict, candidate, list(answer.missing), answer.reason, result.attempts)


def _shown(
    decision: ReuseDecision, index: IndexData, settings: Settings
) -> list[tuple[str, Candidate, str]]:
    """(label, candidate, its code and one entry) for the closest candidates, whole, within the
    context budget (one that doesn't fit is left out, never cut)."""
    reuse, ctx = settings.generate.reuse, settings.context
    chunks = {c.id: c for c in index.chunks}
    budget = ctx.max_tokens
    shown: list[tuple[str, Candidate, str]] = []
    ranked = sorted(decision.candidates, key=lambda c: -c.flow)
    for candidate in ranked:
        if len(shown) >= reuse.coverage_candidates or candidate.flow < reuse.coverage_min_flow:
            break
        chunk = chunks.get(candidate.chunk_id)
        if chunk is None:
            continue
        entry = next(iter(chunk.data_entries.values()), None)
        data = json.dumps(entry, indent=1) if entry is not None else "(no data entry)"
        text = f"```python\n{chunk.code}\n```\n\nData entry:\n\n```json\n{data}\n```"
        cost = estimate_tokens(text, ctx.chars_per_token)
        if cost > budget:
            continue
        budget -= cost
        shown.append((f"T{len(shown) + 1}", candidate, text))
    return shown
