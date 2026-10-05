"""Test-case drafts: what the LLM returns (wire models) and what the pipeline stores."""

from __future__ import annotations

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
    confidence: float = Field(ge=0.0, le=1.0)


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


# --- Stored models -------------------------------------------------------------------------


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
    confidence: float = Field(ge=0.0, le=1.0)
    prompt_version: str


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
