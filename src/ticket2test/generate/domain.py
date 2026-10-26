"""Domains are folders: which one does a ticket belong to?

A domain is a folder matching ``generate.domain_globs`` (``*`` is one folder level), named
after its last part, or an explicit entry of ``generate.domains`` (name -> folder globs). Once a
ticket's domain is known, reuse decisions and generation look only at tests in that domain.

Choosing the domain is code, no LLM: retrieval already ranked the repo's chunks for the ticket,
so the hit scores are summed per domain (the folder where the best-matching tests and page
objects live wins), plus a bonus when the ticket's components or labels, or the draft's
component, name the domain. If the top two are close, the choice is flagged as uncertain.

The reporter's routing comes first: when the ticket's own components name exactly one domain,
that is the domain (the step-7 eval had three tickets whose component named the right folder
while retrieval and the draft's broader component pointed elsewhere).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.models.ticket import Ticket
from ticket2test.validate.claims import norm

COMPONENT_BONUS = 0.25  # added when the ticket's component or the draft's names the domain
LABEL_BONUS = 0.1  # added when one of the ticket's labels names it


@dataclass(frozen=True)
class Domain:
    name: str
    folders: tuple[str, ...]  # repo-relative POSIX folders

    def contains(self, path: str) -> bool:
        return any(path == f or path.startswith(f + "/") for f in self.folders)


@dataclass
class DomainChoice:
    domain: Domain | None
    scores: dict[str, float] = field(default_factory=dict)  # name -> share (0..1 + bonus)
    uncertain: bool = False
    reason: str = ""


def full_match(path: str, pattern: str) -> bool:
    """Glob match by folder level: ``*`` never crosses ``/``."""
    parts, wanted = path.split("/"), pattern.strip("/").split("/")
    return len(parts) == len(wanted) and all(
        fnmatchcase(p, w) for p, w in zip(parts, wanted, strict=True)
    )


def domains(index: IndexData, settings: Settings) -> list[Domain]:
    gen = settings.generate
    folders = {
        str(parent)
        for chunk in index.chunks
        if chunk.kind == "test"
        for parent in PurePosixPath(chunk.file_path).parents
        if str(parent) != "."
    }
    if gen.domains:
        return [
            Domain(name, tuple(sorted(f for f in folders if any(full_match(f, g) for g in globs))))
            for name, globs in sorted(gen.domains.items())
        ]
    found = sorted(f for f in folders if any(full_match(f, g) for g in gen.domain_globs))
    return [Domain(PurePosixPath(f).name, (f,)) for f in found]


def domain_of(path: str, all_domains: list[Domain]) -> Domain | None:
    return next((d for d in all_domains if d.contains(path)), None)


def choose_domain(
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    ticket: Ticket | None = None,
    draft: TestCaseDraft | None = None,
) -> DomainChoice:
    all_domains = domains(index, settings)
    if not all_domains:
        return DomainChoice(None, reason="no domain folders match generate.domain_globs")
    by_name = {d.name: d for d in all_domains}
    ticket_components = list(ticket.components) if ticket else list(retrieval.ticket_components)
    named = [d for d in all_domains if any(_words(d.name) & _words(c) for c in ticket_components)]
    if len(named) == 1:  # the reporter routed the ticket: that is the domain
        return DomainChoice(
            named[0], {named[0].name: 1.0}, False, f"{named[0].name}: the ticket's component"
        )
    if len(named) > 1:  # a cross-area ticket: the area whose class is marked with all of them
        marked = [d for d in named if _has_class_marked(d, ticket_components, index, settings)]
        if len(marked) == 1:
            return DomainChoice(
                marked[0],
                {marked[0].name: 1.0},
                False,
                f"{marked[0].name}: holds a class marked with the ticket's components",
            )
    totals = dict.fromkeys(by_name, 0.0)
    for hit in retrieval.hits:
        found = domain_of(hit.file_path, all_domains)
        if found is not None:
            totals[found.name] += max(hit.score, 0.0)
    chunks = {c.id: c for c in index.chunks}
    for template in retrieval.templates:
        chunk = chunks.get(template.chunk_id)
        found = domain_of(chunk.file_path, all_domains) if chunk else None
        if found is not None:
            totals[found.name] += max(totals.values() or [0.0]) * 0.1  # a nudge, not a vote
    total = sum(totals.values())
    shares = {n: (v / total if total else 0.0) for n, v in totals.items()}
    components, labels = _named(ticket, draft, retrieval)
    for name in shares:
        if _words(name) & components:
            shares[name] += COMPONENT_BONUS
        elif _words(name) & labels:
            shares[name] += LABEL_BONUS
    ranked = sorted(shares.items(), key=lambda kv: (-kv[1], kv[0]))
    best, best_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = settings.generate.reuse.domain_margin
    uncertain = best_score <= 0.0 or best_score - second < margin
    reason = f"{best} {best_score:.2f}" + (
        f" vs {ranked[1][0]} {second:.2f}" if len(ranked) > 1 else ""
    )
    return DomainChoice(
        by_name[best] if best_score > 0 else None,
        {n: round(s, 3) for n, s in ranked},
        uncertain,
        reason,
    )


def _has_class_marked(
    domain: Domain, components: list[str], index: IndexData, settings: Settings
) -> bool:
    """The domain has a test class whose component marker names exactly these components."""
    wanted = {c.strip().lower() for c in components if c.strip()}
    sep = settings.markers.value_separator
    for path, record in index.files.items():
        if record.info is None or not domain.contains(path):
            continue
        for cls in record.info.classes:
            for text in cls.decorators:
                if text.split("(", 1)[0].strip().endswith("mark.component"):
                    values = re.findall(r"""["']([^"']+)["']""", text)
                    parts = {
                        p.strip().lower() for v in values for p in (v.split(sep) if sep else [v])
                    }
                    if parts == wanted:
                        return True
    return False


def _named(
    ticket: Ticket | None, draft: TestCaseDraft | None, retrieval: RetrievalResult
) -> tuple[set[str], set[str]]:
    """(words of the ticket's components and the draft's component, words of its labels)."""
    components: set[str] = set()
    labels: set[str] = set()
    for text in ticket.components if ticket else retrieval.ticket_components:
        components |= _words(text)
    for text in ticket.labels if ticket else retrieval.ticket_labels:
        labels |= _words(text)
    if draft is not None:
        components |= _words(draft.markers.component)
    return components, labels


def _words(text: str) -> set[str]:
    """Stemmed words, so a component "file download" names the folder "files"."""
    return {norm(w) for w in re.split(r"[^a-z0-9]+", text.lower()) if w}
