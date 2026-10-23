"""Check a guide against the index before it is stored: names that don't exist are removed.

Every ref (class, page object, helper, example) must name something that exists in the repo:
defined in it, or referenced by its code (``self.check.assertEqual`` is used by the tests,
though ``unittest`` defines it). Prose mentions in backticks that match nothing (not a name in
the code, a data key at any depth, or a literal value from the data or decorators) are kept but
listed as unverified for the reviewer.

The first real run (2026-10-23) flagged nested data keys, request methods, decorator values
and ``unittest`` assertions; none were invented, so those count as known now.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

from ticket2test.index.indexer import IndexData
from ticket2test.models.guide import GuideOutput, GuideRef
from ticket2test.models.suite_map import AreaSummary
from ticket2test.suitemap.build import referenced_names

_BACKTICKED = re.compile(r"`([^`\n]{1,200})`")
_NAME = re.compile(r"^[A-Za-z_][\w.]*(\(\))?$")
_QUOTED = re.compile(r"""["']([^"'\n]{1,60})["']""")


def check_guide(
    guide: GuideOutput, area: AreaSummary, index: IndexData
) -> tuple[GuideOutput, list[str], list[str]]:
    """The guide without unknown refs, the removed refs (with reasons), and unverified
    mentions."""
    known = _Known(index)
    area_classes = {c.name for c in area.classes}
    removed: list[str] = []

    def keep(refs: list[GuideRef], kind: str, ok: Callable[[str], bool]) -> list[GuideRef]:
        kept: list[GuideRef] = []
        for ref in refs:
            if ok(ref.name.strip()):
                kept.append(ref)
            else:
                removed.append(f"{kind} {ref.name!r}: not in the index")
        return kept

    catalog = index.catalog

    def is_class(name: str) -> bool:
        return name in area_classes or catalog.class_named(name) is not None

    def is_page_object(name: str) -> bool:
        bare = name.removesuffix("()")
        if catalog.resolve_chain_from_roots(bare).ok:
            return True
        owner, _, member = bare.rpartition(".")
        cls = catalog.class_named(owner) if owner else catalog.class_named(bare)
        if cls is None:
            return False
        return not member or member in catalog.members_of(cls.qualname)

    checked = guide.model_copy(
        update={
            "classes": keep(guide.classes, "class", is_class),
            "page_objects": keep(guide.page_objects, "page object", is_page_object),
            "helpers": keep(guide.helpers, "helper", known.code_name),
            "examples": keep(guide.examples, "example", lambda n: n in known.chunk_ids),
        }
    )
    return checked, removed, sorted(_unknown_mentions(checked, known))


class _Known:
    """What counts as existing: names in the code, data keys and literal values."""

    def __init__(self, index: IndexData) -> None:
        self.index = index
        self.chunk_ids = {c.id for c in index.chunks}
        catalog = index.catalog
        self.names = referenced_names(index) | {
            name for c in catalog.classes.values() for name in (c.name, *c.members)
        }
        self.names |= {s.name for s in catalog.symbols}
        self.words: set[str] = {"true", "false", "null", "True", "False", "None"}
        for chunk in index.chunks:
            for entry in chunk.data_entries.values():
                self.words |= set(_keys_and_values(entry))
            for decorator in chunk.decorators:
                self.words |= set(_QUOTED.findall(decorator))
            for marker in chunk.markers:
                self.words |= {str(a) for a in marker.args}

    def code_name(self, name: str) -> bool:
        bare = name.removesuffix("()")
        if bare in self.chunk_ids or self.index.catalog.resolve_chain_from_roots(bare).ok:
            return True
        parts = bare.split(".")
        return parts[-1] in self.names and all(p in self.names or p == "self" for p in parts)

    def mention(self, name: str) -> bool:
        bare = name.removesuffix("()")
        return self.code_name(name) or bare in self.words or bare.split(".")[-1] in self.words


def _unknown_mentions(guide: GuideOutput, known: _Known) -> set[str]:
    texts = [guide.summary, *guide.how_to_add, *guide.data, *guide.pitfalls]
    texts += [r.use for r in (*guide.classes, *guide.page_objects, *guide.helpers, *guide.examples)]
    unknown: set[str] = set()
    for text in texts:
        for mention in _BACKTICKED.findall(text):
            name = mention.strip()
            if _NAME.match(name) and not known.mention(name):
                unknown.add(name)
    return unknown


def _keys_and_values(value: Any, depth: int = 0) -> Iterator[str]:
    """Keys at any depth and short string values of a data entry (bounded depth)."""
    if depth > 12:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _keys_and_values(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _keys_and_values(item, depth + 1)
    elif isinstance(value, str) and len(value) <= 60:
        yield value
