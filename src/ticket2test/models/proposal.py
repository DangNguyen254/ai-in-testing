"""Missing-piece proposals (agent 2): one new member for an existing test-side class, written
by the LLM, checked by code, and kept as a separate patch for review. Existing code never
changes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProposalResponse(BaseModel):
    """The LLM's structured output (``prompts/proposal_v*.md``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    member: str = Field(min_length=1, max_length=120)  # the name the test needs
    kind: Literal["method", "property"]
    code: str = Field(min_length=1, max_length=6000)  # the member's source, decorators included
    rationale: str = Field(max_length=500)  # which existing members it builds on, in a sentence


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_class: str  # qualname of the class that gets the member
    member: str
    kind: Literal["method", "property"] | None = None
    file_path: str  # repo-relative file of the class
    needed_for: str = ""
    ok: bool = False  # every check passed
    findings: list[str] = Field(default_factory=list)  # check failures of the last attempt
    diff: str = ""  # the patch, when one was built
    code: str = ""  # the member as proposed (last attempt)
    rationale: str = ""
    attempts: int = 0  # LLM calls, retries and repairs included
    collect_ok: bool | None = None  # the suite with the patch collects (None: not run)
    prompt_version: str = ""
    model: str = ""
