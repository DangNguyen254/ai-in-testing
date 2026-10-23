"""Area guides: what a strong model writes once per area of the suite, for a weaker model to
read on every ticket (``prompts/guide_v*.md``, ``guides/``)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.llm.meter import Usage


class GuideRef(BaseModel):
    """A name from the material and what it is for. The name is checked against the index."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=300)
    use: str = Field(max_length=400)


class GuideOutput(BaseModel):
    """The fixed outline of a guide (the LLM's structured output)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(max_length=1200)  # what the area's tests check, in a few sentences
    how_to_add: list[str] = Field(max_length=12)  # ordered steps for a new test in this area
    classes: list[GuideRef] = Field(max_length=12)  # test classes: when to put a test where
    page_objects: list[GuideRef] = Field(max_length=25)  # chains such as nav.<area>.<page>
    helpers: list[GuideRef] = Field(max_length=20)  # base-class helpers and functions
    data: list[str] = Field(max_length=12)  # how entries look: sections, keys, placeholders
    examples: list[GuideRef] = Field(max_length=8)  # test chunk ids worth copying
    pitfalls: list[str] = Field(max_length=10)  # what the examples alone wouldn't show


class AreaGuide(BaseModel):
    """A stored guide, after the code check."""

    model_config = ConfigDict(extra="forbid")

    area: str
    digest: str  # the area summary's digest it was built from
    sources: dict[str, str]  # path -> sha256 (from the area summary)
    model: str
    prompt_version: str
    built_at: datetime
    input_pieces: list[str]  # what the model was shown (summary, chunk ids)
    input_tokens_estimate: int
    guide: GuideOutput
    removed: list[str] = Field(default_factory=list)  # refs dropped by the check, with reason
    unverified: list[str] = Field(default_factory=list)  # `names` in the prose not in the index
    usage: Usage | None = None
    cost_usd: float | None = None  # reported by the provider, or tokens x configured prices


class GuidePlanItem(BaseModel):
    """One area in a guides run: its estimate and what happened."""

    model_config = ConfigDict(extra="forbid")

    area: str
    tests: int
    status: Literal[
        "up_to_date", "planned", "built", "failed", "over_budget", "over_limit", "stopped"
    ]
    input_tokens_estimate: int
    max_output_tokens: int
    cost_estimate_usd: float | None  # worst case: estimated input + the full output cap
    cost_usd: float | None = None  # actual, when built
    usage: Usage | None = None
    removed: int = 0
    unverified: int = 0
    seconds: float | None = None
    note: str = ""


class GuideRun(BaseModel):
    """A guides run (or an estimate): the plan per area and the totals."""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    created_at: datetime
    model: str
    prompt_version: str
    estimate_only: bool
    budget_usd: float
    ceiling_usd: float
    prices_known: bool  # input/output prices configured for the model
    items: list[GuidePlanItem]
    spent_usd: float = 0.0
    stopped: str = ""  # why the run stopped early, if it did
