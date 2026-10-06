"""Heuristic: do the test's checks cover what its docstring, its name, and the draft claim?

Deterministic and deliberately simple. It never blocks a test; it produces warnings for the
reviewer, e.g. "page 2 shows only allow rules" checked only by a count.

- Claims: the outcome steps of the docstring (the last numbered step, and any step with an
  outcome word such as "shows", "stays", "kept"), the draft's expected outcome, and the test
  name. Each is split into clauses at "and", ",", ";".
- Evidence: the words of each check call (identifiers split at ``_`` / camel case, string
  literals, numbers), the data keys it reads and their values in the entries, and for a
  validation helper the entry's expectation section.
- A clause is covered when one of its content words appears in the evidence of some check
  (lenient on purpose, so the warnings stay rare: "the page change" is covered by any check
  on a page property).
  A clause with "only", "remaining", "every", or "all" also needs an item-level check: one
  that compares the shown items (a plural, non-count property such as ``rule_actions``, a
  ``set(...)`` / ``sorted(...)``, or ``assertIn`` / ``assertNotIn``), not just a count.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any

from ticket2test.index.tokens import split_identifier
from ticket2test.validate.code import CheckCall, dotted


def _word_set(text: str) -> frozenset[str]:
    return frozenset(text.split())


_STOP = _word_set(
    """a an the is are be been was were it its this that these those of to in on at by for
    with from as and or but not no still again also then than there their they them his her
    shows show shown displays display see sees visible appears appear listed lists list
    stays stay remains remain kept keeps keep has have had contains contain gets get
    should must can will would does do did same new one each when after before into out
    up down only all every remaining any some user page's test tests check checks"""
)
_QUALIFIERS = frozenset({"only", "remaining", "every", "all"})
_OUTCOME_WORDS = _word_set(
    """shows displays stays remains kept keeps listed lists appears gone blocked contains
    has have is are only remaining unchanged visible still"""
)
# A step starting with one of these is an action, unless it starts with a checking word.
_IMPERATIVE = _word_set(
    """add save select open search filter go click delete turn change enter type navigate
    publish reset edit import create log fill remove set seed apply cancel confirm press"""
)
_CHECKING = _word_set("check verify ensure expect assert")
_COUNT_WORDS = frozenset({"count", "total", "len", "length", "size", "number"})
_ITEM_CALLS = frozenset({"set", "sorted", "list", "frozenset"})
_ITEM_ASSERTS = frozenset({"assertIn", "assertNotIn", "assertCountEqual", "assertListEqual"})
_STEP = re.compile(r"^\s*(\d+)[.)]\s*(.+)$")
_WORD = re.compile(r"[A-Za-z]+|\d+")


@dataclass(frozen=True)
class Gap:
    source: str  # "docstring", "expected outcome", "name"
    clause: str
    reason: str  # "not checked" or "checked only by a count"


def outcome_claims(doc: str) -> list[str]:
    """Outcome steps of a numbered docstring (or its last sentence when not numbered)."""
    steps = [m.group(2).strip() for line in doc.splitlines() if (m := _STEP.match(line))]
    if not steps:
        sentences = [s.strip() for s in re.split(r"[.\n]", doc) if s.strip()]
        return sentences[-1:]
    picked = [s for s in steps if _is_outcome(s)]
    return picked or steps[-1:]


def _is_outcome(step: str) -> bool:
    first = (_WORD.findall(step.lower()) or [""])[0]
    if first in _CHECKING:
        return True
    if first in _IMPERATIVE:
        return False
    return bool(_words(step) & _OUTCOME_N)


def clauses(claim: str) -> list[str]:
    parts = re.split(r",|;|\band\b|\bbut\b", claim)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def evidence(
    check: CheckCall,
    entries: list[dict[str, Any]],
    sections: dict[str, str],
    ignore: frozenset[str] = frozenset(),
) -> set[str]:
    """Words a check touches. ``ignore``: attribute names that carry no meaning (``params``)."""
    words: set[str] = set()
    node = check.node
    for inner in ast.walk(node):
        if isinstance(inner, ast.Attribute) and inner.attr not in ignore:
            # local variable names are not evidence
            words.update(norm(w) for w in split_identifier(inner.attr))
        elif _is_empty(inner):
            words.update(_EMPTY)
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str | int):
            words.update(norm(w) for w in _WORD.findall(str(inner.value)))
            if isinstance(inner.value, str):
                for entry in entries:  # a data key: its values count too
                    if inner.value in entry:
                        words.update(_words(json.dumps(entry[inner.value])))
    if check.helper:
        for section, helper in sections.items():
            if helper == check.method:
                for entry in entries:
                    blocks = [entry, *(t for t in entry.get("tenants", []) if isinstance(t, dict))]
                    for block in blocks:
                        words.update(_words(json.dumps(block.get(section, ""))))
    return words


def item_level(check: CheckCall, ignore: frozenset[str] = frozenset()) -> bool:
    """Compares the shown items, not only how many there are."""
    if check.helper or check.method in _ITEM_ASSERTS:
        return True
    for inner in ast.walk(check.node):
        if isinstance(inner, ast.Call) and dotted(inner.func) in _ITEM_CALLS:
            return True
        if isinstance(inner, ast.List | ast.Set):
            return True
        if isinstance(inner, ast.Attribute) and inner.attr not in ignore:
            parts = split_identifier(inner.attr)
            plural = bool(parts) and parts[-1].endswith("s") and not set(parts) & _COUNT_WORDS
            if plural and not _inside_len(inner, check.node):
                return True
    return False


def find_gaps(
    claims: list[tuple[str, str]],
    checks: list[CheckCall],
    entries: list[dict[str, Any]],
    sections: dict[str, str],
    ignore: frozenset[str] = frozenset(),
    actions: set[str] | None = None,
) -> list[Gap]:
    """``claims``: (source, text) pairs. Returns the clauses no check covers.

    ``ignore``: attribute names that carry no meaning (the data access and assertion object).
    ``actions``: words of the page-object steps the test uses (evidence for a name claim).
    """
    per_check = [(c, evidence(c, entries, sections, ignore)) for c in checks]
    gaps: list[Gap] = []
    for source, claim in claims:
        for clause in clauses(claim):
            content = _content(clause)
            if not content:
                continue
            matching = [c for c, words in per_check if _overlap(content, words)]
            if not matching:
                # A name only claims what the test touches: its actions count as evidence.
                if source == "name" and actions and _overlap(content, actions):
                    continue
                gaps.append(Gap(source, clause, "not checked"))
            elif _words(clause) & _QUALIFIERS_N and not any(
                item_level(c, ignore) for c in matching
            ):
                gaps.append(Gap(source, clause, "checked only by a count or a single value"))
    return gaps


def name_claim(function_name: str, test_prefix: str, generic: set[str]) -> str:
    """The test name as a claim, without the prefix and generic words (e.g. the area)."""
    words = [w for w in split_identifier(function_name) if w != test_prefix and w not in generic]
    return " ".join(words)


_EMPTY = frozenset({"empty", "zero", "none", "no"})


def _is_empty(node: ast.AST) -> bool:
    """0, "", [], {}, set(): a check against these supports "empty" / "none" claims."""
    if isinstance(node, ast.Constant):
        return node.value in (0, "") and not isinstance(node.value, bool)
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _overlap(claim: set[str], evidence: set[str]) -> bool:
    """Shared words, or one word a prefix of the other (at least 4 letters: edit / editor)."""
    if claim & evidence:
        return True
    return any(
        len(short) >= 4 and long.startswith(short)
        for c in claim
        for e in evidence
        for short, long in ((c, e), (e, c))
    )


def _content(clause: str) -> set[str]:
    return {w for w in _words(clause) if w not in _STOP_N and (len(w) > 2 or w.isdigit())}


def _words(text: str) -> set[str]:
    return {norm(w) for w in _WORD.findall(text)}


def norm(word: str) -> str:
    """Lower case and a light stem, so "rules" matches "rule" and "selected" "select"."""
    w = word.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def _inside_len(node: ast.AST, root: ast.AST) -> bool:
    for inner in ast.walk(root):
        if (
            isinstance(inner, ast.Call)
            and dotted(inner.func) == "len"
            and any(node in ast.walk(arg) for arg in inner.args)
        ):
            return True
    return False


# The word sets in the form ``_words`` produces.
_STOP_N = frozenset(norm(w) for w in _STOP)
_QUALIFIERS_N = frozenset(norm(w) for w in _QUALIFIERS)
_OUTCOME_N = frozenset(norm(w) for w in _OUTCOME_WORDS)
