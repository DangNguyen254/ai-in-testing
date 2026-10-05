"""Deterministic query building: ticket (+ draft) text, and code identifiers found in it."""

from __future__ import annotations

import re

from ticket2test.index.catalog import SymbolCatalog
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.ticket import Ticket

_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[a-z][A-Z]|[A-Z]{2,}[a-z]")
_MAX_IDENTIFIERS = 30


def ticket_text(ticket: Ticket, draft: TestCaseDraft | None = None, max_chars: int = 6000) -> str:
    parts = [ticket.title, ticket.description or "", *ticket.steps_to_reproduce]
    parts += [ticket.expected or "", ticket.actual or ""]
    if draft is not None:
        parts += [draft.intent, draft.markers.component, *draft.steps, draft.expected_outcome]
    text = "\n".join(p for p in parts if p)
    return text[:max_chars]


def candidate_identifiers(text: str) -> list[str]:
    """Words that look like code: dotted names, snake_case, CamelCase, called names.

    Capitalized single words ("Client") are kept too; ``verify_identifiers`` only accepts
    them if a class of that name exists, which filters sentence-start English words.
    """
    found: dict[str, None] = {}
    for dotted in _DOTTED.findall(text):
        found.setdefault(dotted, None)
        for part in dotted.split("."):
            found.setdefault(part, None)
    for match in _WORD.finditer(text):
        word = match.group(0)
        called = text[match.end() : match.end() + 1] == "("
        if "_" in word.strip("_") or _CAMEL.search(word) or called or word[:1].isupper():
            found.setdefault(word, None)
    return list(found)[:200]


def verify_identifiers(names: list[str], catalog: SymbolCatalog) -> tuple[list[str], list[str]]:
    """Split into (names that exist in the repo, names that don't). Order is kept."""
    classes = {c.name for c in catalog.classes.values()}
    symbol_names = {s.name for s in catalog.symbols if s.kind != "module"}
    verified: list[str] = []
    rejected: list[str] = []
    for name in names:
        last = name.rsplit(".", 1)[-1]
        if len(last) < 3 or not _WORD.fullmatch(last):
            continue
        plain_capitalized = last[:1].isupper() and "_" not in last and not _CAMEL.search(last)
        known = last in classes if plain_capitalized else last in symbol_names
        target = verified if known else rejected
        if last not in verified and last not in rejected:
            target.append(last)
    return verified[:_MAX_IDENTIFIERS], rejected[:_MAX_IDENTIFIERS]
