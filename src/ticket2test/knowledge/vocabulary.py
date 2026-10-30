"""The suite's vocabulary for one ticket: what the draft and the generation context are told
(docs/knowledge-plan.md, steps C3 and C4).

- For the draft (which runs before retrieval, without the index): the glossary terms the ticket
  names, with the suite's words for them (folders, classes, component markers, data values), and
  the known values of the matched areas, from the suite map (``ticket2test map``). The component
  markers of the matched terms become the draft's component choices.
- For generation: the known values, in the template's folder, of the keys its entry uses
  (computed from the index, so always current).

It adds no facts: it translates the ticket's words into the suite's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData
from ticket2test.knowledge.glossary import GlossaryError, Term, load_glossary, match_terms
from ticket2test.models.chunk import Chunk
from ticket2test.models.suite_map import KeyValues
from ticket2test.models.ticket import Ticket


@dataclass
class DraftVocabulary:
    text: str = ""  # the block for the draft prompt ("" when nothing matched)
    components: list[str] = field(default_factory=list)  # marker values of the matched terms
    terms: list[str] = field(default_factory=list)


def draft_vocabulary(ticket: Ticket, settings: Settings) -> DraftVocabulary:
    k = settings.knowledge
    if not k.use_in_draft:
        return DraftVocabulary()
    try:
        glossary = load_glossary(k.glossary)
    except GlossaryError:
        return DraftVocabulary()
    if glossary is None:
        return DraftVocabulary()
    terms = match_terms(ticket, glossary)
    if not terms:
        return DraftVocabulary()
    lines = [_term_line(t) for t in terms]
    values = _map_values(terms, settings)
    if values:
        lines.append("Values the suite's data uses in those areas (key path: values):")
        lines += [f"  - {v.key}: {', '.join(c.name for c in v.values)}" for v in values]
    components = list(dict.fromkeys(m for t in terms for m in t.markers))
    if not components:  # the entries list none: the component markers the suite uses there
        components = _map_components(terms, settings)
    return DraftVocabulary("\n".join(lines), components, [t.term for t in terms])


def _term_line(term: Term) -> str:
    parts = []
    if term.folders:
        parts.append(f"tested in {', '.join(term.folders)}")
    if term.classes:
        parts.append(f"classes {', '.join(c.rsplit('::', 1)[-1] for c in term.classes)}")
    if term.markers:
        parts.append(f"component marker {', '.join(term.markers)}")
    for item in term.data:
        if item.values:
            parts.append(f"{item.key} = {', '.join(item.values)}")
    if term.chains:
        parts.append(f"pages {', '.join(term.chains)}")
    return f'- "{term.term}" in the suite: ' + ("; ".join(parts) or "(no details)")


def _term_folders(terms: list[Term]) -> list[str]:
    return [f.strip("/") for t in terms for f in t.folders] + [
        str(PurePosixPath(c.split("::", 1)[0]).parent) for t in terms for c in t.classes
    ]


def _matched_areas(terms: list[Term], settings: Settings) -> list[Any]:
    """The suite map's areas under the matched terms' folders (and their classes' folders)."""
    from ticket2test.suitemap import load_map

    folder = map_dir(settings)
    suite_map = load_map(folder) if folder is not None else None
    wanted = _term_folders(terms)
    if suite_map is None or not wanted:
        return []
    return [
        area
        for area in suite_map.areas
        if any(
            a == w or a.startswith(w + "/") or w.startswith(a + "/")
            for a in area.folders
            for w in wanted
        )
    ]


_MAX_COMPONENTS = 3


def _map_components(terms: list[Term], settings: Settings) -> list[str]:
    """The component marker values the tests in the matched areas use, most common first."""
    sep = settings.markers.value_separator
    counts: dict[str, int] = {}
    for area in _matched_areas(terms, settings):
        for marker in area.markers:
            name, _, args = marker.name.partition("=")
            if name != "component" or not args:
                continue
            for value in args.split(sep) if sep else [args]:
                if value.strip():
                    counts[value.strip()] = counts.get(value.strip(), 0) + marker.count
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ranked[:_MAX_COMPONENTS]]


def _map_values(terms: list[Term], settings: Settings) -> list[KeyValues]:
    """Low-cardinality known values of the areas under the matched folders (from map.json)."""
    k = settings.knowledge
    found: dict[str, KeyValues] = {}
    for area in _matched_areas(terms, settings):
        for v in area.data_values:
            if not v.free_text and v.values and v.distinct <= k.max_vocabulary_values:
                found.setdefault(v.key, v)
    ranked = sorted(found.values(), key=lambda v: -v.entries)
    return ranked[: k.max_vocabulary_keys]


def map_dir(settings: Settings) -> Path | None:
    """``knowledge.map_dir``, else ``<output_dir>/map/<repo folder name>`` (``paths.repo``)."""
    if settings.knowledge.map_dir is not None:
        return settings.knowledge.map_dir
    if settings.paths.repo is None:
        return None
    return settings.paths.output_dir / "map" / _safe(settings.paths.repo.resolve().name)


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)


# --- generation --------------------------------------------------------------------------------


def entry_values(
    template: Chunk,
    entry: dict[str, Any],
    index: IndexData,
    settings: Settings,
    for_context: bool = True,
) -> list[KeyValues]:
    """For the keys the template entry uses: the values the entries of tests in the template's
    folder give them (free text and keys with many values left out). ``for_context``: for the
    generation context (``knowledge.use_in_generation``, at most ``max_vocabulary_keys`` keys);
    False: every key, for checks in code."""
    from ticket2test.suitemap.build import known_values, leaves

    if for_context and not settings.knowledge.use_in_generation:
        return []
    folder = str(PurePosixPath(template.file_path).parent)
    entries = [
        e
        for c in index.chunks
        if c.kind == "test" and str(PurePosixPath(c.file_path).parent) == folder
        for e in c.data_entries.values()
        if isinstance(e, dict)
    ]
    paths = {p for p, _ in leaves(entry, "", 0)}
    k = settings.knowledge
    found = [
        v
        for v in known_values(entries, settings, keys=paths)
        if v.key in paths and not v.free_text and v.values and v.distinct <= k.max_vocabulary_values
    ]
    return found[: k.max_vocabulary_keys] if for_context else found


def render_entry_values(values: list[KeyValues]) -> str:
    return "\n".join(
        f"- `{v.key}`: " + ", ".join(json.dumps(c.name, ensure_ascii=False) for c in v.values)
        for v in values
    )
