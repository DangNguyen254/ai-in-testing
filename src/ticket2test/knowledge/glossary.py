"""The tracker-to-suite glossary (``knowledge.glossary``, a private YAML file).

A model session that can read the private suite writes and updates it (``docs/glossary-prompt.md``);
the tool only reads it. Each term maps a tracker word (a component, an epic, a label, or a phrase
from ticket text) to the suite's words: folders, areas, classes, component marker values, data keys
with their values, page-object chains. The file is living: the tool records what it can't use, the
ticket words the glossary doesn't know yet and mapped names the suite no longer has, in the
``knowledge.unmapped_log`` list, for the next update.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ticket2test.models.ticket import Ticket

TermKind = Literal["component", "epic", "label", "phrase"]
_SPACING = re.compile(r"[\s_\-]+")
_EPIC_LINE = re.compile(r"(?mi)^\s*epic\s*:\s*(.+?)\s*$")


class GlossaryError(ValueError):
    """The glossary file exists but can't be read; the message says why."""


class DataValues(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    values: list[str] = Field(default_factory=list)


class Term(BaseModel):
    model_config = ConfigDict(extra="ignore")  # a writer may add fields; unknown ones are kept out

    term: str
    kind: TermKind = "component"
    status: Literal["proposed", "confirmed"] = "proposed"
    checked: str | None = None
    folders: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)  # path::ClassName
    markers: list[str] = Field(default_factory=list)
    data: list[DataValues] = Field(default_factory=list)
    chains: list[str] = Field(default_factory=list)
    note: str = ""
    evidence: list[str] = Field(default_factory=list)


class UnmappedTerm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    term: str
    kind: TermKind = "component"
    reason: str = ""


class Glossary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    updated: str | None = None
    terms: list[Term] = Field(default_factory=list)
    unmapped: list[UnmappedTerm] = Field(default_factory=list)

    def known(self, word: str) -> bool:
        """The glossary has the word, mapped or listed as unmapped."""
        key = normalized(word)
        names = [t.term for t in self.terms] + [u.term for u in self.unmapped]
        return any(normalized(name) == key for name in names)


def normalized(word: str) -> str:
    """For matching: case, spaces, underscores and hyphens don't matter."""
    return _SPACING.sub(" ", word).strip().lower()


_CACHE: dict[Path, tuple[float, Glossary]] = {}


def load_glossary(path: Path | None) -> Glossary | None:
    """The glossary at ``path``; None when no path is set or the file doesn't exist yet."""
    if path is None or not path.is_file():
        return None
    mtime = path.stat().st_mtime
    cached = _CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise GlossaryError(f"{path}: expected a mapping with 'terms'")
        for value in ("updated",):  # YAML turns 2026-10-29 into a date
            if isinstance(raw.get(value), date):
                raw[value] = raw[value].isoformat()
        for term in raw.get("terms") or []:
            if isinstance(term, dict) and isinstance(term.get("checked"), date):
                term["checked"] = term["checked"].isoformat()
        glossary = Glossary.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise GlossaryError(f"{path}: {exc}") from exc
    _CACHE[path] = (mtime, glossary)
    return glossary


def ticket_words(ticket: Ticket) -> list[str]:
    """The ticket's routing words: components, labels (a pasted ticket's type and epic are
    labels) and an "Epic: <name>" line in the description."""
    words = [*ticket.components, *ticket.labels]
    words += _EPIC_LINE.findall(ticket.description or "")
    return list(dict.fromkeys(w.strip() for w in words if w.strip()))


def match_terms(ticket: Ticket, glossary: Glossary) -> list[Term]:
    """Terms the ticket names: a routing word equal to a term (any kind, spacing and case
    ignored), or a phrase term found in the title or description as whole words."""
    words = {normalized(w) for w in ticket_words(ticket)}
    text = normalized(f"{ticket.title} {ticket.description or ''}")
    found: list[Term] = []
    for term in glossary.terms:
        key = normalized(term.term)
        if not key:
            continue
        if key in words or (
            term.kind == "phrase" and re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text)
        ):
            found.append(term)
    return found


def unknown_words(ticket: Ticket, glossary: Glossary) -> list[str]:
    """The ticket's routing words the glossary has neither mapped nor listed as unmapped."""
    return [w for w in ticket_words(ticket) if not glossary.known(w)]


def record_unmapped(
    log: Path, ticket_id: str, words: list[str], stale: list[str], today: str | None = None
) -> None:
    """Append what the glossary lacks to the log (one line each, never twice):
    ``unknown<TAB>word<TAB>ticket`` for a word it doesn't know, ``stale<TAB>what<TAB>ticket``
    for a mapped name the suite no longer has."""
    lines = [("unknown", w) for w in words] + [("stale", s) for s in stale]
    if not lines:
        return
    seen: set[tuple[str, str]] = set()
    if log.is_file():
        for row in log.read_text(encoding="utf-8").splitlines():
            parts = row.split("\t")
            if len(parts) >= 2:
                seen.add((parts[0], normalized(parts[1])))
    new = [(k, v) for k, v in lines if (k, normalized(v)) not in seen]
    if not new:
        return
    log.parent.mkdir(parents=True, exist_ok=True)
    stamp = today or date.today().isoformat()
    with log.open("a", encoding="utf-8") as out:
        for kind, value in new:
            out.write(f"{kind}\t{value}\t{ticket_id}\t{stamp}\n")


def unmapped_log_path(settings_path: Path | None, glossary: Path | None) -> Path | None:
    """``knowledge.unmapped_log``, else next to the glossary (``<glossary>-unmapped.txt``)."""
    if settings_path is not None:
        return settings_path
    if glossary is None:
        return None
    return glossary.with_name(f"{glossary.stem}-unmapped.txt")
