"""Retrieval pipeline.

query (deterministic + optional LLM rewrite) -> BM25 + grep -> reciprocal-rank fusion
-> AST-style expansion (callees, callers, related tests, page objects) -> capped LLM
follow-up rounds (own search tools only), or the investigator agent when enabled
(retrieve/investigator.py) -> ranked hits with reasons + JSON-entry templates.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData
from ticket2test.knowledge import (
    GlossaryError,
    Term,
    load_glossary,
    match_terms,
    record_unmapped,
    unknown_words,
    unmapped_log_path,
)
from ticket2test.llm.base import LLMClient
from ticket2test.models.chunk import Chunk
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.retrieval import (
    FollowupSearch,
    Investigation,
    QueryRewrite,
    Reason,
    RetrievalResult,
    RetrievedChunk,
    TemplateRef,
)
from ticket2test.models.ticket import Ticket
from ticket2test.prompts import load_prompt
from ticket2test.retrieve.investigator import investigate
from ticket2test.retrieve.llm_steps import request_followups, rewrite_query
from ticket2test.retrieve.query import candidate_identifiers, ticket_text, verify_identifiers
from ticket2test.retrieve.rerank import Ranked, in_places, rerank
from ticket2test.retrieve.shape import shape_of_draft, shape_of_test

log = logging.getLogger(__name__)

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

    def count_containing(self, identifier: str) -> int:
        """How many chunks define or reference the identifier (no cap)."""
        return len(self._containing(identifier))

    def definitions_of(self, identifier: str) -> list[Chunk]:
        return list(self._definitions.get(identifier, []))

    def users_of(self, identifier: str) -> list[Chunk]:
        """Chunks whose syntax tree references the identifier."""
        return list(self._users.get(identifier, []))

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
        self,
        pool: dict[str, _Candidate],
        draft: TestCaseDraft | None,
        ticket_components: list[str] | None = None,
    ) -> list[TemplateRef]:
        """Tests with data entries: same component first, then the draft's shape (UI or API,
        then add / edit / delete / other; see ``retrieve/shape.py``), then retrieval score.

        The component comes from the draft and from the ticket's own components; a free-text
        draft component ("rule search") also matches a component word it contains ("rule[s]").
        """
        wanted = {c.strip().lower() for c in (ticket_components or []) if c.strip()}
        if draft is not None:
            wanted.add(draft.markers.component.strip().lower())
        words = {w for c in wanted for w in re.findall(r"[a-z0-9]+", c)}
        with_data = [c for c in pool.values() if c.chunk.kind == "test" and c.chunk.data_entries]

        def component_of(candidate: _Candidate) -> str | None:
            for value in (
                str(a).lower()
                for m in candidate.chunk.markers
                if m.name == "component"
                for a in m.args
            ):
                singular = value.removesuffix("s")
                if value in wanted or value in words or (singular and singular in words):
                    return value
            return None

        wanted_shape = shape_of_draft(draft, self.settings) if draft is not None else None

        def shape_gap(candidate: _Candidate) -> tuple[int, int]:
            if wanted_shape is None:
                return 0, 0
            return wanted_shape.distance(shape_of_test(candidate.chunk, self.settings))

        ranked = sorted(
            with_data,
            key=lambda c: (component_of(c) is None, shape_gap(c), -c.score, c.chunk.id),
        )
        refs: list[TemplateRef] = []
        for candidate in ranked[: self.cfg.max_templates]:
            key = next(i for i in candidate.chunk.test_ids if i in candidate.chunk.data_entries)
            matched = component_of(candidate)
            why = f"same component '{matched}'" if matched else "most similar test with data"
            if wanted_shape is not None and shape_gap(candidate) == (0, 0):
                why += f", same shape ({wanted_shape.kind} {wanted_shape.action})"
            refs.append(TemplateRef(chunk_id=candidate.chunk.id, entry_key=key, why=why))
            candidate.add_reason(Reason(source="template", detail=f"template entry {key}"))
        return refs


def _glossary_terms(ticket: Ticket, index: IndexData, settings: Settings) -> list[Term]:
    """The glossary terms the ticket names; what the glossary lacks goes to the unmapped log
    (words it doesn't know, mapped folders and classes the suite no longer has)."""
    path = settings.knowledge.glossary
    try:
        glossary = load_glossary(path)
    except GlossaryError as exc:
        log.warning("Glossary not used: %s", exc)
        return []
    if glossary is None:
        return []
    matched = match_terms(ticket, glossary)
    folders = {str(p) for c in index.chunks for p in PurePosixPath(c.file_path).parents}
    classes = {f"{c.file_path}::{c.symbol_name}" for c in index.chunks if c.kind != "test"}
    stale = [
        f"{t.term}: folder {f}" for t in matched for f in t.folders if f.strip("/") not in folders
    ] + [f"{t.term}: class {c}" for t in matched for c in t.classes if c not in classes]
    log_path = unmapped_log_path(settings.knowledge.unmapped_log, path)
    if log_path is not None:
        try:
            record_unmapped(log_path, ticket.id, unknown_words(ticket, glossary), stale)
        except OSError as exc:
            log.warning("Unmapped words not recorded: %s", exc)
    return matched  # a stale folder or class simply matches nothing


def _glossary_words(terms: list[Term]) -> str:
    """Search words from matched terms: class names, chains, component markers, data keys and
    values (identifiers are split into words by the search itself)."""
    words: list[str] = []
    for term in terms:
        words += [c.rsplit("::", 1)[-1] for c in term.classes]
        words += term.chains + term.markers
        for item in term.data:
            words += [item.key.replace("[]", " ").replace(".", " "), *item.values]
    return " ".join(dict.fromkeys(w for w in words if w))


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

    matched = _glossary_terms(ticket, index, settings)
    places = (
        [p for t in matched for p in [*t.folders, *t.classes]]
        if settings.knowledge.use_in_search
        else []
    )
    guessed = candidate_identifiers(text) + (rewrite.identifiers if rewrite else [])
    identifiers, rejected = verify_identifiers(guessed, retriever.catalog)

    def ranked_top(current: dict[str, _Candidate]) -> list[Ranked]:
        return _final(current, identifiers, text, settings, places)

    lists: list[RankedList] = [retriever.bm25(text, "query=ticket")]
    if rewrite is not None and rewrite.terms:
        lists.append(retriever.bm25(" ".join(rewrite.terms), "query=rewrite"))
    lists.extend(retriever.grep(name) for name in identifiers)

    pool = _build_pool(retriever, lists)
    rounds = 0
    searches_run = ["bm25: <ticket text>"] + (["bm25: <rewrite terms>"] if rewrite else [])
    if places and not any(in_places(r.chunk, places) for r in ranked_top(pool)):
        # the ticket's own words missed every place the glossary names: search in its words
        fallback = [retriever.grep(c.rsplit("::", 1)[-1]) for t in matched for c in t.classes]
        words = _glossary_words(matched)
        if words:
            fallback.append(retriever.bm25(words, "query=glossary"))
        lists.extend(fallback)
        pool = _build_pool(retriever, lists)
        searches_run.append("bm25: <glossary terms> (the ticket's words found none of its places)")
    searches_run += [f"grep: {name}" for name in identifiers]
    investigation: Investigation | None = None
    if use_llm and cfg.investigator.enabled:
        assert client is not None
        prompt = load_prompt(cfg.investigator.prompt, settings.paths.prompts_dir)
        investigation = investigate(
            client,
            prompt,
            retriever,
            text,
            _describe(ranked_top(pool)),
            settings,
        )
        llm_calls += investigation.llm_calls
        prompt_versions.append(prompt.version)
        kept = [
            (retriever.chunks[k.chunk_id], Reason(source="investigator", detail=k.why))
            for k in investigation.kept
        ]
        if kept:
            lists.append(kept)
            pool = _build_pool(retriever, lists)
    elif use_llm and cfg.max_followup_rounds > 0:
        assert client is not None
        prompt = load_prompt(cfg.followup_prompt, settings.paths.prompts_dir)
        for round_no in range(1, cfg.max_followup_rounds + 1):
            if not _is_thin(ranked_top(pool), cfg.top_k, cfg.followup_min_tests):
                break
            response = request_followups(
                client,
                prompt,
                text,
                searches_run,
                _describe(ranked_top(pool)),
                settings,
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

    templates = retriever.templates(pool, draft, ticket.components)
    final = ranked_top(pool)
    if investigation is not None:  # what the investigator kept stays, even below the top_k
        in_final = {r.chunk.id for r in final}
        final += [
            Ranked(chunk=pool[k.chunk_id].chunk, fused=pool[k.chunk_id].score, score=0.0,
                   features={})
            for k in investigation.kept
            if k.chunk_id not in in_final
        ]  # fmt: skip
    hits = [
        RetrievedChunk(
            chunk_id=r.chunk.id,
            file_path=r.chunk.file_path,
            qualname=r.chunk.qualname,
            kind=r.chunk.kind,
            start_line=r.chunk.start_line,
            score=r.score,
            fused_score=round(r.fused, 6),
            rank_features=r.features,
            reasons=pool[r.chunk.id].reasons,
        )
        for r in final
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
        investigation=investigation,
        llm_calls=llm_calls,
        prompt_versions=prompt_versions,
        glossary_terms=[t.term for t in matched],
        glossary_folders=list(dict.fromkeys(f for t in matched for f in t.folders)),
        ticket_components=list(ticket.components),
        ticket_labels=list(ticket.labels),
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


def _final(
    pool: dict[str, _Candidate],
    identifiers: list[str],
    text: str,
    settings: Settings,
    places: list[str] | None = None,
) -> list[Ranked]:
    candidates = [(c.chunk, c.score, [r.detail for r in c.reasons]) for c in pool.values()]
    return rerank(
        candidates,
        identifiers,
        text,
        settings.retrieval.top_k,
        settings.retrieval.rerank,
        places or (),
    )


def _is_thin(top: list[Ranked], k: int, min_tests: int) -> bool:
    return len(top) < k or sum(r.chunk.kind == "test" for r in top) < min_tests


def _describe(top: list[Ranked]) -> list[str]:
    return [
        f"{i}. [{c.chunk.kind}] {c.chunk.qualname} ({c.chunk.file_path})"
        for i, c in enumerate(top, 1)
    ]


def _same_file_first(chunks: list[Chunk], file_path: str) -> list[Chunk]:
    unique = list({c.id: c for c in chunks}.values())
    return sorted(unique, key=lambda c: c.file_path != file_path)
