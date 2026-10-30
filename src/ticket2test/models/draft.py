"""Test-case drafts: what the LLM returns (wire models) and what the pipeline stores."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

DraftKind = Literal["primary", "edge_case"]
DraftStatus = Literal["ok", "insufficient_info"]
MissingInfo = Literal["steps_to_reproduce", "expected_behavior"]
TestKind = Literal["ui", "api", "hybrid"]
DeploymentType = Literal["cloud", "on_prem", "both"]

UNKNOWN = "unknown"
MAX_EDGE_CASES = 3

# Validation context keys (allowed marker values come from config, not from the model).
CTX_PRIORITIES = "priorities"
CTX_SUITES = "suites"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VariantInput(_Frozen):
    name: str
    value: str


class Variant(_Frozen):
    """One parametrized case of a test (later: one parametrize entry + one JSON data entry)."""

    name: str
    inputs: list[VariantInput]
    expected: str


class DraftMarkers(_Frozen):
    priority: str
    component: str  # "unknown" when it can't be inferred
    suite: str  # "unknown" when it can't be determined

    @field_validator("priority")
    @classmethod
    def _known_priority(cls, value: str, info: ValidationInfo) -> str:
        allowed = _allowed(info, CTX_PRIORITIES)
        if allowed is not None and value not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return value

    @field_validator("suite")
    @classmethod
    def _known_suite(cls, value: str, info: ValidationInfo) -> str:
        allowed = _allowed(info, CTX_SUITES)
        if allowed is not None and value not in [*allowed, UNKNOWN]:
            raise ValueError(f"suite must be one of {[*allowed, UNKNOWN]}")
        return value


def _allowed(info: ValidationInfo, key: str) -> list[str] | None:
    context: Any = info.context
    if isinstance(context, dict) and isinstance(context.get(key), list):
        return list(context[key])
    return None


# --- Wire models: the JSON shape the LLM must return ---------------------------------------


class DraftItem(_Frozen):
    kind: DraftKind
    intent: str = Field(min_length=1)
    markers: DraftMarkers
    test_kind: TestKind
    deployment_type: DeploymentType
    preconditions: list[str]
    steps: list[str] = Field(min_length=1)
    expected_outcome: str = Field(min_length=1)
    variants: list[Variant]


class DraftResponse(_Frozen):
    status: DraftStatus
    missing_info: list[MissingInfo]
    reason: str
    drafts: list[DraftItem]

    @model_validator(mode="after")
    def _consistent(self) -> DraftResponse:
        if self.status == "insufficient_info":
            if not self.missing_info:
                raise ValueError("status 'insufficient_info' requires a non-empty missing_info")
            if self.drafts:
                raise ValueError("status 'insufficient_info' must have an empty drafts list")
            return self
        if self.missing_info:
            raise ValueError("status 'ok' must have an empty missing_info list")
        primaries = sum(1 for d in self.drafts if d.kind == "primary")
        edges = sum(1 for d in self.drafts if d.kind == "edge_case")
        if primaries != 1:
            raise ValueError(f"status 'ok' needs exactly 1 primary draft, got {primaries}")
        if edges > MAX_EDGE_CASES:
            raise ValueError(f"at most {MAX_EDGE_CASES} edge_case drafts allowed, got {edges}")
        return self


# --- Partial draft skeleton (for tickets with insufficient info) ---------------------------

CTX_TICKET_TEXT = "ticket_text"  # the ticket as sent to the LLM: numbers must come from it
_QUESTION_REF = re.compile(r"\[(Q\d+)\]")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")


class OpenQuestion(_Frozen):
    id: str = Field(pattern=r"^Q\d+$")  # "Q1"
    question: str = Field(min_length=1)  # for the ticket's reporter or developer
    why: str  # what the test can't decide without the answer


class DraftSkeleton(_Frozen):
    """A partial draft for discussion: what the ticket supports, with every unknown left as a
    question (``[Q1]`` in the text). Never used for generation; the ticket stays
    ``insufficient_info`` until the questions are answered."""

    intent: str = Field(min_length=1)
    test_kind: TestKind | Literal["unknown"]
    preconditions: list[str]
    steps: list[str] = Field(min_length=1)
    expected_outcome: str = Field(min_length=1)
    open_questions: list[OpenQuestion] = Field(min_length=1)
    notes: str

    @model_validator(mode="after")
    def _honest(self, info: ValidationInfo) -> DraftSkeleton:
        texts = [self.intent, *self.preconditions, *self.steps, self.expected_outcome]
        ids = [q.id for q in self.open_questions]
        if len(ids) != len(set(ids)):
            raise ValueError("open_questions ids must be unique")
        used = {ref for t in texts for ref in _QUESTION_REF.findall(t)}
        unknown = sorted(used - set(ids))
        if unknown:
            raise ValueError(f"the text refers to questions that don't exist: {unknown}")
        unused = sorted(set(ids) - used)
        if unused:
            raise ValueError(
                f"questions {unused} are never referenced: mark where each unknown sits with "
                "[Qn] in the preconditions, steps, or expected outcome"
            )
        context: Any = info.context
        ticket = context.get(CTX_TICKET_TEXT) if isinstance(context, dict) else None
        if isinstance(ticket, str):
            body = _QUESTION_REF.sub("", " ".join(texts))
            invented = sorted({n for n in _NUMBER.findall(body) if n not in ticket})
            if invented:
                raise ValueError(
                    f"numbers {invented} are not in the ticket: never fill in a value; leave "
                    "it as a question ([Qn])"
                )
        return self


# --- Stored models -------------------------------------------------------------------------


class DraftSupport(_Frozen):
    """How well a draft is supported by its ticket, checked in code (see draft/support.py)."""

    explicit_steps: bool  # the ticket has a steps-to-reproduce section
    explicit_expected: bool  # ... an expected-behavior section
    explicit_actual: bool  # ... an actual-behavior section
    component_from_ticket: bool  # the draft's component is named in the ticket
    invented_numbers: list[str]  # numbers in the draft that the ticket doesn't contain
    grounding: float = Field(ge=0.0, le=1.0)  # share of the draft's content words in the ticket
    ungrounded_words: list[str]  # the draft's words the ticket doesn't have (most frequent)
    # Variants none of whose input values the ticket names: a split the draft made up (one
    # payload vs several, when the ticket names one). Shown for review; nothing is dropped.
    ungrounded_variants: list[str] = Field(default_factory=list)


class TestCaseDraft(_Frozen):
    __test__ = False  # not a pytest test class

    id: str  # "<ticket id>/d1"
    ticket_id: str
    kind: DraftKind
    intent: str
    markers: DraftMarkers
    test_kind: TestKind
    deployment_type: DeploymentType
    preconditions: list[str]
    steps: list[str]
    expected_outcome: str
    variants: list[Variant]
    prompt_version: str
    support: DraftSupport | None = None  # checked in code (draft/support.py)

    @model_validator(mode="before")
    @classmethod
    def _drop_self_rating(cls, data: Any) -> Any:
        """Drafts written before 2026-10-08 carry the LLM's self-rated ``confidence``; it was
        removed (a model's score of its own output isn't evidence). Old files still load."""
        if isinstance(data, dict) and "confidence" in data:
            data = {k: v for k, v in data.items() if k != "confidence"}
        return data


class DraftResult(_Frozen):
    """Everything one ``draft`` run produced for one ticket."""

    ticket_id: str
    status: DraftStatus
    missing_info: list[MissingInfo] = Field(default_factory=list)
    reason: str = ""
    drafts: list[TestCaseDraft] = Field(default_factory=list)
    prompt_version: str
    provider: str
    model: str
    attempts: int = Field(ge=0)  # LLM calls made (0 = decided without the LLM)
    redactions: int = Field(default=0, ge=0)  # secrets scrubbed from prompt + output
    # insufficient_info only: a partial draft with open questions (never generated from)
    skeleton: DraftSkeleton | None = None
    skeleton_prompt_version: str | None = None
