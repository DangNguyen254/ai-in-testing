"""Retrieval results: ranked chunks, each with the reasons it was retrieved."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.models.chunk import ChunkKind

ReasonSource = Literal["bm25", "grep", "expansion", "followup", "template", "investigator"]


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
    score: float  # after reranking
    fused_score: float | None = None  # before reranking
    rank_features: dict[str, float] = Field(default_factory=dict)
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


InvestigatorTool = Literal[
    "search",
    "grep",
    "open",
    "open_member",
    "callers",
    "tests_using",
    "chain",
    "class_hierarchy",
    "list_members",
    "data",
    "data_entry",
]


class InvestigatorAction(BaseModel):
    """One read-only tool call the investigator asks for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: InvestigatorTool
    arg: str = Field(min_length=1, max_length=200)  # a query, identifier, chunk id or chain


class KeptChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    why: str = Field(max_length=300)


class MissingHint(BaseModel):
    """A piece the new test needs that the investigator couldn't find: a page-object member,
    a helper or a fixture. Hints only; code checks each one (gaps/) before it is used."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["page_object_member", "helper", "fixture"]
    owner: str = Field(max_length=200)  # class or page-object chain; "" for a module function
    name: str = Field(min_length=1, max_length=120)  # the name it would have
    needed_for: str = Field(max_length=300)  # the draft step that needs it


class InvestigatorStep(BaseModel):
    """What the investigator returns each turn (``prompts/investigator_v*.md``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    thought: str = Field(max_length=600)  # what it is looking for next, in a sentence or two
    actions: list[InvestigatorAction] = Field(max_length=6)
    keep: list[KeptChunk] = Field(max_length=15)  # chunks the test needs (cumulative)
    missing: list[MissingHint] = Field(max_length=10)  # needed pieces it couldn't find
    done: bool


class Investigation(BaseModel):
    """The investigator's run, kept for traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: int
    tool_calls: list[str]  # "search('...') -> 8 results"
    kept: list[KeptChunk]
    missing: list[MissingHint]
    dropped_ids: list[str] = Field(default_factory=list)  # kept ids that don't exist
    stopped: Literal["done", "budget", "no_actions"]
    llm_calls: int


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
    investigation: Investigation | None = None  # when the investigator ran
    llm_calls: int = 0
    prompt_versions: list[str] = Field(default_factory=list)
    # The ticket's own routing hints, kept for later steps (domain choice in `generate`).
    ticket_components: list[str] = Field(default_factory=list)
    ticket_labels: list[str] = Field(default_factory=list)
