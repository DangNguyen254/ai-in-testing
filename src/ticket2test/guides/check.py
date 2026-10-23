"""Check a guide against the index before it is stored: names that don't exist are removed.

Every ref (class, page object, helper, example) must name something that exists; prose
mentions in backticks that don't match anything in the index are kept but listed as
unverified for the reviewer (they may be literal values, not names).
"""

from __future__ import annotations

import re

from ticket2test.index.indexer import IndexData
from ticket2test.models.guide import GuideOutput, GuideRef
from ticket2test.models.suite_map import AreaSummary

_BACKTICKED = re.compile(r"`([^`\n]{1,200})`")
_NAME = re.compile(r"^[A-Za-z_][\w.]*(\(\))?$")


def check_guide(
    guide: GuideOutput, area: AreaSummary, index: IndexData
) -> tuple[GuideOutput, list[str], list[str]]:
    """The guide without unknown refs, the removed refs (with reasons), and unverified
    mentions."""
    catalog = index.catalog
    chunk_ids = {c.id for c in index.chunks}
    member_names = {name for c in catalog.classes.values() for name in c.members}
    area_classes = {c.name for c in area.classes}
    removed: list[str] = []

    def keep(refs: list[GuideRef], kind: str, known: object) -> list[GuideRef]:
        kept: list[GuideRef] = []
        for ref in refs:
            if known(ref.name.strip()):  # type: ignore[operator]
                kept.append(ref)
            else:
                removed.append(f"{kind} {ref.name!r}: not in the index")
        return kept

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

    def is_helper(name: str) -> bool:
        bare = name.removesuffix("()").rsplit(".", 1)[-1]
        return bare in member_names or bool(catalog.find(bare))

    checked = guide.model_copy(
        update={
            "classes": keep(guide.classes, "class", is_class),
            "page_objects": keep(guide.page_objects, "page object", is_page_object),
            "helpers": keep(guide.helpers, "helper", is_helper),
            "examples": keep(guide.examples, "example", lambda n: n in chunk_ids),
        }
    )
    unverified = sorted(_unknown_mentions(checked, area, index, member_names, chunk_ids))
    return checked, removed, unverified


def _unknown_mentions(
    guide: GuideOutput,
    area: AreaSummary,
    index: IndexData,
    member_names: set[str],
    chunk_ids: set[str],
) -> set[str]:
    texts = [guide.summary, *guide.how_to_add, *guide.data, *guide.pitfalls]
    texts += [r.use for r in (*guide.classes, *guide.page_objects, *guide.helpers, *guide.examples)]
    known_words = (
        {k.name for k in area.data_keys}
        | {m.name.split("=")[0] for m in area.markers}
        | {f.name for f in area.fixtures}
    )
    unknown: set[str] = set()
    for text in texts:
        for mention in _BACKTICKED.findall(text):
            name = mention.strip()
            if not _NAME.match(name):
                continue  # a literal value or an expression, not a name
            bare = name.removesuffix("()")
            last = bare.rsplit(".", 1)[-1]
            if (
                bare in chunk_ids
                or bare in known_words
                or index.catalog.has(bare)
                or index.catalog.resolve_chain_from_roots(bare).ok
                or last in member_names
                or index.catalog.find(last)
            ):
                continue
            unknown.add(name)
    return unknown
