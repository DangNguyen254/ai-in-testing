"""Retrieval results: ranked chunks, each with the reasons it was retrieved."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.models.chunk import ChunkKind

ReasonSource = Literal["bm25", "grep", "expansion", "followup", "template"]


class Reason(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: ReasonSource
    detail: str  # e.g. "query=ticket rank=3", "identifier=base_url", "caller of Client._merge_url"


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    file_path: str
    qualname: str
    kind: ChunkKind
    start_line: int
    score: float
    reasons: list[Reason]


class TemplateRef(BaseModel):
    """An existing test whose JSON entry can serve as the template for a new entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    entry_key: str
    why: str


# --- LLM wire models ------------------------------------------------------------------------


class QueryRewrite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    terms: list[str] = Field(max_length=20)  # words likely to appear in the code
    identifiers: list[str] = Field(max_length=20)  # guessed code names (verified later)
    reason: str


class FollowupSearch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: Literal["bm25", "grep", "symbol"]
    query: str = Field(min_length=1, max_length=200)


class FollowupRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    done: bool
    searches: list[FollowupSearch] = Field(max_length=5)
    reason: str


# --- Result -------------------------------------------------------------------------------------


class RetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    draft_id: str | None = None
    repo_root: str
    query_text: str
    identifiers: list[str] = Field(default_factory=list)  # verified against the catalog
    rewrite: QueryRewrite | None = None
    rejected_identifiers: list[str] = Field(default_factory=list)  # guessed, not in the repo
    hits: list[RetrievedChunk]
    templates: list[TemplateRef] = Field(default_factory=list)
    followup_rounds: int = 0
    llm_calls: int = 0
    prompt_versions: list[str] = Field(default_factory=list)
