"""Test shape: what kind of test (UI or API) and what it does (add, edit, delete, other).

Templates of the same shape give the generator the right flow to copy (an add test's wizard and
publish, a delete test's selection and confirm, a UI-only test's stop before the top bar), so
template ranking prefers them after the component. All in code:

- **kind**: a test is UI when one of its ``self.<root>...`` chains starts at a page-object root
  (``index.chain_roots``), else API; a draft says it (``test_kind``; ``hybrid`` fits both);
- **action**: the first action word (``retrieval.shape_actions``) in the test's name, else in the
  names it calls; for a draft, in its intent, else in its steps. No action word: ``other``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ticket2test.config import Settings
from ticket2test.index.tokens import split_identifier
from ticket2test.models.chunk import Chunk
from ticket2test.models.draft import TestCaseDraft

_WORD = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class Shape:
    kind: str  # "ui", "api", or "hybrid" (drafts only)
    action: str  # an action name from config, or "other"

    def distance(self, other: Shape) -> tuple[int, int]:
        """(kind differs, action differs); smaller is closer."""
        kinds = "hybrid" in (self.kind, other.kind) or self.kind == other.kind
        return int(not kinds), int(self.action != other.action)


def shape_of_test(chunk: Chunk, settings: Settings) -> Shape:
    roots = set(settings.index.chain_roots)
    ui = any(chain and chain[0] in roots for chain in chunk.refs.self_chains)
    actions = settings.retrieval.shape_actions
    action = _action(split_identifier(chunk.symbol_name), actions) or _action(
        [w for name in chunk.refs.names for w in split_identifier(name)], actions
    )
    return Shape("ui" if ui else "api", action or "other")


def shape_of_draft(draft: TestCaseDraft, settings: Settings) -> Shape:
    actions = settings.retrieval.shape_actions
    action = _action(_WORD.findall(draft.intent.lower()), actions) or _action(
        _WORD.findall(" ".join(draft.steps).lower()), actions
    )
    return Shape(draft.test_kind, action or "other")


def _action(words: list[str], actions: dict[str, list[str]]) -> str | None:
    lookup = {w: name for name, synonyms in actions.items() for w in synonyms}
    for word in words:
        for form in _forms(word.lower()):
            if form in lookup:
                return lookup[form]
    return None


def _forms(word: str) -> list[str]:
    """The word and its likely stems: adds/added/adding -> add, deleted/deleting -> delete."""
    forms = [word]
    for suffix, replacements in (
        ("ing", ("", "e")),
        ("ed", ("", "e")),
        ("es", ("",)),
        ("s", ("",)),
    ):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            forms += [word[: -len(suffix)] + r for r in replacements]
    return forms
