"""Retrieval pipeline.

query (deterministic + optional LLM rewrite) -> BM25 + grep -> reciprocal-rank fusion
-> AST-style expansion (callees, callers, related tests, page objects) -> capped LLM
follow-up rounds (own search tools only) -> ranked hits with reasons + JSON-entry templates.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient
from ticket2test.models.chunk import Chunk
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.retrieval import (
    FollowupSearch,
    QueryRewrite,
    Reason,
    RetrievalResult,
    RetrievedChunk,
    TemplateRef,
)
from ticket2test.models.ticket import Ticket
from ticket2test.prompts import load_prompt
from ticket2test.retrieve.llm_steps import request_followups, rewrite_query
from ticket2test.retrieve.query import candidate_identifiers, ticket_text, verify_identifiers

RankedList = list[tuple[Chunk, Reason]]


@dataclass
class _Candidate:
    chunk: Chunk
    score: float = 0.0
    reasons: list[Reason] = field(default_factory=list)

    def add_reason(self, reason: Reason) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)


class Retriever:
    """Search tools over one index. Read-only; every tool is bounded by config."""

    def __init__(self, index: IndexData, settings: Settings) -> None:
        self.index = index
        self.settings = settings
        self.cfg = settings.retrieval
        self.catalog = index.catalog
        self.chunks = {c.id: c for c in index.chunks}
        self._search = index.search_index()
        self._definitions: dict[str, list[Chunk]] = {}
        for chunk in index.chunks:
            if chunk.kind != "test":
                self._definitions.setdefault(chunk.symbol_name, []).append(chunk)
        # Syntax-tree reference index: identifier -> chunks that reference it.
        self._users: dict[str, list[Chunk]] = {}
        for chunk in index.chunks:
            for name in chunk.refs.names:
                self._users.setdefault(name, []).append(chunk)

    # --- tools (also the only tools follow-up rounds may use) ----------------------------

    def bm25(self, query: str, label: str) -> RankedList:
        hits = self._search.search(query, top_k=self.cfg.bm25_candidates)
        return [
            (h.chunk, Reason(source="bm25", detail=f"{label} rank={rank}"))
            for rank, h in enumerate(hits, start=1)
        ]

    def grep(self, identifier: str, label: str = "grep") -> RankedList:
        """Exact identifier search over syntax-tree references: definitions first, then the
        chunks that reference it most (comments, docstrings and strings don't count)."""
        matches = self._containing(identifier)
        if not matches or len(matches) > self.cfg.grep_max_matches:
            return []
        ranked = sorted(
            matches,
            key=lambda c: (c.symbol_name != identifier, -c.refs.names.get(identifier, 0), c.id),
        )
        source = "followup" if label.startswith("followup") else "grep"
        return [
            (c, Reason(source=source, detail=f"{label} identifier={identifier}"))  # type: ignore[arg-type]
            for c in ranked
        ]

    def symbol(self, name: str, label: str) -> RankedList:
        defs = self._definitions.get(name.rsplit(".", 1)[-1], [])
        return [
            (c, Reason(source="followup", detail=f"{label} definition of {name}")) for c in defs
        ]

    def _containing(self, identifier: str) -> list[Chunk]:
        """Chunks that define or reference the identifier (from the syntax tree)."""
        found = {c.id: c for c in self._definitions.get(identifier, [])}
        found.update((c.id, c) for c in self._users.get(identifier, []))
        return [found[i] for i in sorted(found)]

    # --- fusion and expansion ----------------------------------------------------------

    def fuse(self, lists: Iterable[RankedList]) -> dict[str, _Candidate]:
        pool: dict[str, _Candidate] = {}
        for ranked in lists:
            for rank, (chunk, reason) in enumerate(ranked, start=1):
                candidate = pool.setdefault(chunk.id, _Candidate(chunk))
                candidate.score += 1.0 / (self.cfg.rrf_k + rank)
                candidate.add_reason(reason)
        return pool

    def expand(self, pool: dict[str, _Candidate]) -> None:
        seeds = sorted(pool.values(), key=lambda c: (-c.score, c.chunk.id))[
            : self.cfg.expansion_seeds
        ]
        per_seed = self.cfg.expansion_per_seed
        for seed in seeds:
            related: list[tuple[str, list[Chunk]]] = []
            chunk = seed.chunk
            if chunk.kind == "test":
                # A test's useful neighbours are the page objects its chains reach; its other
                # callees are mostly generic helpers (open, click, ...) that crowd out tests.
                related.append(("page object used by", self._page_objects_used(chunk)[:per_seed]))
            else:
                callees = [
                    d
                    for name in chunk.refs.calls
                    if name != chunk.symbol_name
                    for d in self._definitions.get(name, [])
                ]
                related.append(("callee of", _same_file_first(callees, chunk.file_path)[:per_seed]))
                users = [c for c in self._uses_of(chunk) if c.id != chunk.id]
                related.append(("test of", [c for c in users if c.kind == "test"][:per_seed]))
                related.append(("caller of", [c for c in users if c.kind != "test"][:per_seed]))
            for relation, chunks in related:
                for position, target in enumerate(chunks):
                    candidate = pool.setdefault(target.id, _Candidate(target))
                    candidate.score += seed.score * self.cfg.expansion_weight / (1 + position)
                    candidate.add_reason(
                        Reason(source="expansion", detail=f"{relation} {chunk.qualname}")
                    )

    def _uses_of(self, chunk: Chunk) -> list[Chunk]:
        """Chunks that reference this chunk's symbol (syntax tree), unless it's too common."""
        if chunk.symbol_name.startswith("__") or len(chunk.symbol_name) < 3:
            return []
        users = self._users.get(chunk.symbol_name, [])
        return users if len(users) <= self.cfg.grep_max_matches else []

    def _page_objects_used(self, test: Chunk) -> list[Chunk]:
        if test.class_name is None:
            return []
        found: dict[str, Chunk] = {}
        for steps in test.refs.self_chains:
            resolution = self.catalog.resolve_chain(test.class_name, steps)
            for qualname in resolution.types:
                entry = self.catalog.classes.get(qualname) if qualname else None
                if entry is None or qualname not in self.catalog.page_objects:
                    continue
                target = self.chunks.get(f"{entry.file_path}::{entry.name}")
                if target is not None:
                    found.setdefault(target.id, target)
        return list(found.values())

    # --- templates -----------------------------------------------------------------------

    def templates(
        self, pool: dict[str, _Candidate], draft: TestCaseDraft | None
    ) -> list[TemplateRef]:
        component = draft.markers.component.lower() if draft else None
        with_data = [c for c in pool.values() if c.chunk.kind == "test" and c.chunk.data_entries]

        def same_component(candidate: _Candidate) -> bool:
            values = [
                str(a).lower()
                for m in candidate.chunk.markers
                if m.name == "component"
                for a in m.args
            ]
            return component is not None and component in values

        ranked = sorted(with_data, key=lambda c: (not same_component(c), -c.score, c.chunk.id))
        refs: list[TemplateRef] = []
        for candidate in ranked[: self.cfg.max_templates]:
            key = next(i for i in candidate.chunk.test_ids if i in candidate.chunk.data_entries)
            why = (
                f"same component '{component}'"
                if same_component(candidate)
                else "most similar test with data"
            )
            refs.append(TemplateRef(chunk_id=candidate.chunk.id, entry_key=key, why=why))
            candidate.add_reason(Reason(source="template", detail=f"template entry {key}"))
        return refs


def retrieve(
    ticket: Ticket,
    index: IndexData,
    settings: Settings,
    client: LLMClient | None = None,
    draft: TestCaseDraft | None = None,
) -> RetrievalResult:
    cfg = settings.retrieval
    retriever = Retriever(index, settings)
    text = ticket_text(ticket, draft, cfg.max_ticket_chars)
    use_llm = cfg.use_llm and client is not None
    llm_calls = 0
    prompt_versions: list[str] = []

    rewrite: QueryRewrite | None = None
    if use_llm:
        assert client is not None
        prompt = load_prompt(cfg.query_rewrite_prompt, settings.paths.prompts_dir)
        result = rewrite_query(client, prompt, text, settings)
        rewrite, llm_calls = result.value, llm_calls + result.attempts
        prompt_versions.append(prompt.version)

    guessed = candidate_identifiers(text) + (rewrite.identifiers if rewrite else [])
    identifiers, rejected = verify_identifiers(guessed, retriever.catalog)

    lists: list[RankedList] = [retriever.bm25(text, "query=ticket")]
    if rewrite is not None and rewrite.terms:
        lists.append(retriever.bm25(" ".join(rewrite.terms), "query=rewrite"))
    lists.extend(retriever.grep(name) for name in identifiers)

    pool = _build_pool(retriever, lists)
    rounds = 0
    searches_run = ["bm25: <ticket text>"] + (["bm25: <rewrite terms>"] if rewrite else [])
    searches_run += [f"grep: {name}" for name in identifiers]
    if use_llm and cfg.max_followup_rounds > 0:
        assert client is not None
        prompt = load_prompt(cfg.followup_prompt, settings.paths.prompts_dir)
        for round_no in range(1, cfg.max_followup_rounds + 1):
            if not _is_thin(_top(pool, cfg.top_k), cfg.top_k, cfg.followup_min_tests):
                break
            response = request_followups(
                client, prompt, text, searches_run, _describe(_top(pool, cfg.top_k)), settings
            )
            llm_calls += response.attempts
            rounds = round_no
            if cfg.followup_prompt not in prompt_versions:
                prompt_versions.append(prompt.version)
            request = response.value
            new_lists = _run_followups(
                retriever, request.searches[: cfg.followup_max_searches], round_no, searches_run
            )
            before = set(pool)
            lists.extend(new_lists)
            pool = _build_pool(retriever, lists)
            if request.done or set(pool) == before:
                break

    templates = retriever.templates(pool, draft)
    hits = [
        RetrievedChunk(
            chunk_id=c.chunk.id,
            file_path=c.chunk.file_path,
            qualname=c.chunk.qualname,
            kind=c.chunk.kind,
            start_line=c.chunk.start_line,
            score=round(c.score, 6),
            reasons=c.reasons,
        )
        for c in _top(pool, cfg.top_k)
    ]
    return RetrievalResult(
        ticket_id=ticket.id,
        draft_id=draft.id if draft else None,
        repo_root=index.repo_root,
        query_text=text,
        identifiers=identifiers,
        rewrite=rewrite,
        rejected_identifiers=rejected,
        hits=hits,
        templates=templates,
        followup_rounds=rounds,
        llm_calls=llm_calls,
        prompt_versions=prompt_versions,
    )


def _build_pool(retriever: Retriever, lists: list[RankedList]) -> dict[str, _Candidate]:
    pool = retriever.fuse(lists)
    retriever.expand(pool)
    return pool


def _run_followups(
    retriever: Retriever,
    searches: list[FollowupSearch],
    round_no: int,
    searches_run: list[str],
) -> list[RankedList]:
    lists: list[RankedList] = []
    for search in searches:
        label = f"followup round={round_no} {search.tool}"
        searches_run.append(f"{search.tool}: {search.query}")
        if search.tool == "bm25":
            ranked = [
                (c, Reason(source="followup", detail=f"{label} query={search.query!r} {r.detail}"))
                for c, r in retriever.bm25(search.query, "")
            ]
        elif search.tool == "grep":
            names, _ = verify_identifiers([search.query.strip()], retriever.catalog)
            ranked = retriever.grep(names[0], label) if names else []
        else:
            ranked = retriever.symbol(search.query.strip(), label)
        lists.append(ranked)
    return lists


def _top(pool: dict[str, _Candidate], k: int) -> list[_Candidate]:
    return sorted(pool.values(), key=lambda c: (-c.score, c.chunk.id))[:k]


def _is_thin(top: list[_Candidate], k: int, min_tests: int) -> bool:
    return len(top) < k or sum(c.chunk.kind == "test" for c in top) < min_tests


def _describe(top: list[_Candidate]) -> list[str]:
    return [
        f"{i}. [{c.chunk.kind}] {c.chunk.qualname} ({c.chunk.file_path})"
        for i, c in enumerate(top, 1)
    ]


def _same_file_first(chunks: list[Chunk], file_path: str) -> list[Chunk]:
    unique = list({c.id: c for c in chunks}.values())
    return sorted(unique, key=lambda c: c.file_path != file_path)
