"""How well a draft is supported by its ticket: facts checked in code, never a model's score.

For each draft:

- **explicit steps / expected / actual**: the normalized ticket has that section (the normalizer
  pulls "Steps to reproduce", "Expected", "Actual" into their own fields); without them the
  draft was inferred from free text;
- **component from the ticket**: a word of the draft's component is in the ticket's components,
  labels, or title (the draft didn't name a component the ticket doesn't);
- **invented numbers**: numbers in the draft that the ticket doesn't contain;
- **grounding**: the share of the draft's content words (preconditions, steps, expected
  outcome, variants) found in the ticket, and the words that aren't (what the draft added).
"""

from __future__ import annotations

import re

from ticket2test.models.draft import DraftSupport
from ticket2test.models.ticket import Ticket
from ticket2test.validate.claims import norm

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")  # 4+ characters: content words
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")
_COMMON = frozenset(
    norm(w)
    for w in [
        "that",
        "this",
        "these",
        "those",
        "with",
        "from",
        "into",
        "onto",
        "when",
        "then",
        "than",
        "there",
        "their",
        "they",
        "them",
        "have",
        "has",
        "had",
        "does",
        "done",
        "make",
        "made",
        "should",
        "would",
        "could",
        "will",
        "must",
        "been",
        "being",
        "were",
        "what",
        "which",
        "while",
        "where",
        "after",
        "before",
        "about",
        "again",
        "also",
        "only",
        "each",
        "every",
        "some",
        "other",
        "same",
        "such",
        "very",
        "more",
        "most",
        "first",
        "last",
        "next",
        "open",
        "click",
        "page",
        "check",
        "verify",
        "ensure",
        "make",
        "sure",
        "using",
        "used",
        "user",
    ]
)
MAX_SHOWN = 10


def ticket_text(ticket: Ticket) -> str:
    parts = [
        ticket.title,
        ticket.description,
        *ticket.steps_to_reproduce,
        ticket.expected,
        ticket.actual,
        *ticket.labels,
        *ticket.components,
        *(c.body for c in ticket.comments),
    ]
    return "\n".join(p for p in parts if p)


def support_for(ticket: Ticket, component: str, texts: list[str]) -> DraftSupport:
    """``texts``: the draft's preconditions, steps, expected outcome, and variant texts."""
    source = ticket_text(ticket)
    source_words = {norm(w) for w in _WORD.findall(source)}
    raw = [w.lower() for t in texts for w in _WORD.findall(t)]
    content = [(norm(w), w) for w in raw if norm(w) not in _COMMON]
    grounded = [stem for stem, _ in content if stem in source_words]
    missing: dict[str, int] = {}
    spelled: dict[str, str] = {}  # stem -> the draft's first spelling (shown to the reviewer)
    for stem, word in content:
        if stem not in source_words:
            missing[stem] = missing.get(stem, 0) + 1
            spelled.setdefault(stem, word)
    named = " ".join([*ticket.components, *ticket.labels, ticket.title]).lower()
    component_words = {norm(w) for w in _WORD.findall(component)} - _COMMON
    named_words = {norm(w) for w in _WORD.findall(named)}
    return DraftSupport(
        explicit_steps=bool(ticket.steps_to_reproduce),
        explicit_expected=bool((ticket.expected or "").strip()),
        explicit_actual=bool((ticket.actual or "").strip()),
        component_from_ticket=bool(component_words & named_words),
        invented_numbers=sorted({n for t in texts for n in _NUMBER.findall(t) if n not in source}),
        grounding=round(len(grounded) / len(content), 2) if content else 1.0,
        ungrounded_words=[
            spelled[w] for w in sorted(missing, key=lambda w: (-missing[w], w))[:MAX_SHOWN]
        ],
    )
