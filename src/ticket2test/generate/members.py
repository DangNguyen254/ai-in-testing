"""Member cards for the generation context: one line per member the new test can call.

The template and the similar tests show the calls *they* make; a step the draft needs and
none of them has is otherwise only a name in a chain list, or absent. A card says what a
member is (action or value), what it takes, and what its docstring and body say it does, for
the helpers of the test's class and its bases and for the page objects its class reaches.
Built from the index (no LLM), ranked by the draft's words, capped.
"""

from __future__ import annotations

import re

from ticket2test.config import Settings
from ticket2test.generate.context import Piece
from ticket2test.index.catalog import ClassEntry
from ticket2test.index.extract import ClassInfo, FunctionInfo
from ticket2test.index.indexer import IndexData
from ticket2test.index.tokens import split_identifier, tokenize
from ticket2test.models.chunk import Chunk
from ticket2test.models.draft import TestCaseDraft

_RETURNS = re.compile(r"^\s*return\s+(?!None\b)\S", re.MULTILINE)
_DOC_CHARS = 100


def member_cards_piece(
    draft: TestCaseDraft,
    template: Chunk,
    page_objects: list[str],
    index: IndexData,
    settings: Settings,
) -> Piece | None:
    """``page_objects``: qualnames of the pages the context already reaches (the template's
    and the examples'); the pages the other tests of the template's class reach are added."""
    cards = _cards(template, page_objects, index, settings)
    lines = member_cards(draft, template, page_objects, index, settings)
    if not lines:
        return None
    return Piece(
        "Members this test can call (one line each: use the one that does a step instead of "
        "writing the step out, also when the template doesn't call it)",
        "\n".join(lines)
        + (f"\n({len(cards) - len(lines)} more not listed)" if len(cards) > len(lines) else ""),
    )


def member_cards(
    draft: TestCaseDraft,
    template: Chunk,
    page_objects: list[str],
    index: IndexData,
    settings: Settings,
) -> list[str]:
    """The card lines, the draft's words first, at most ``generate.member_cards_max``."""
    wanted = set(
        tokenize(
            " ".join([draft.intent, *draft.preconditions, *draft.steps, draft.expected_outcome])
        )
    )
    cards = _cards(template, page_objects, index, settings)
    # the draft's words first (most shared words first), the rest in the suite's own order
    ranked = sorted(enumerate(cards), key=lambda item: (-len(wanted & item[1][1]), item[0]))
    return [line for _, (line, _) in ranked[: settings.generate.member_cards_max]]


def _cards(
    template: Chunk, page_objects: list[str], index: IndexData, settings: Settings
) -> list[tuple[str, set[str]]]:
    return [*_helper_cards(template, index, settings), *_page_cards(template, page_objects, index)]


def _helper_cards(
    template: Chunk, index: IndexData, settings: Settings
) -> list[tuple[str, set[str]]]:
    """The non-test methods of the template's class and of its in-repo bases."""
    catalog = index.catalog
    entry = catalog.class_named(template.class_name or "")
    if entry is None:
        return []
    prefix = settings.index.test_function_prefix
    hooks = set(settings.generate.scaffold_methods)
    seen: set[str] = set()
    cards: list[tuple[str, set[str]]] = []
    for owner in catalog.mro(entry.qualname):
        info = _class_info(owner, index)
        for method in info.methods if info is not None else []:
            name = method.name
            if name in seen or name in hooks or name.startswith((prefix, "_")):
                continue
            seen.add(name)
            cards.append(_card(f"self.{name}", method, _is_property(method), owner.name))
    return cards


def _page_cards(
    template: Chunk, page_objects: list[str], index: IndexData
) -> list[tuple[str, set[str]]]:
    """The members of the page objects in play, each by a chain that reaches it."""
    catalog = index.catalog
    pages = set(page_objects)
    for chunk in index.chunks:  # the pages the class's other tests reach
        if (
            chunk.kind == "test"
            and chunk.file_path == template.file_path
            and chunk.class_name == template.class_name
        ):
            for steps in chunk.refs.self_chains:
                for qualname in catalog.resolve_chain(chunk.class_name or "", steps).types:
                    if qualname in catalog.page_objects:
                        pages.add(qualname)
    seen: set[tuple[str, str]] = set()
    own: list[tuple[str, set[str]]] = []
    inherited: list[tuple[str, set[str]]] = []  # a shared base page's members, once, last
    for chain in catalog.chains:
        name = chain.chain.rsplit(".", 1)[-1]
        if chain.owner not in pages or chain.kind == "attribute" or name.startswith("_"):
            continue
        if chain.type in catalog.classes:  # a step on the way to a page, not a member to use
            continue
        found = catalog.member(chain.owner, name)
        definer = found[0] if found is not None else catalog.classes[chain.owner]
        if (definer.qualname, name) in seen:  # the same member by another chain or page
            continue
        seen.add((definer.qualname, name))
        info = _class_info(definer, index)
        method = next((m for m in info.methods if m.name == name), None) if info else None
        owner = catalog.classes[chain.owner].name
        cards = own if definer.qualname == chain.owner else inherited
        if method is None:
            words = set(split_identifier(name)) | set(split_identifier(owner))
            cards.append((f"- `self.{chain.chain}` ({chain.kind}, {owner})", words))
        else:
            cards.append(_card(f"self.{chain.chain}", method, chain.kind == "property", owner))
    return [*own, *inherited]


def _card(call: str, method: FunctionInfo, is_property: bool, owner: str) -> tuple[str, set[str]]:
    """The line, and the words it is ranked by (its name, its owner's, its docstring's)."""
    doc = " ".join((method.docstring or "").split())
    first = doc.split(". ")[0][:_DOC_CHARS].rstrip(".")
    if is_property:
        head = f"`{call}` (value, {owner})"
    else:
        params = ", ".join(p.name for p in method.params if p.name not in ("self", "cls"))
        head = f"`{call}({params})` (action, {owner})"
    facts = []
    if not is_property and _RETURNS.search(method.code):
        facts.append("returns a value")
    if re.search(r"\bassert\w*\b", method.code):
        facts.append("asserts")
    line = f"- {head}" + (f": {first}" if first else "")
    if facts:
        line += f" [{'; '.join(facts)}]"
    words = set(split_identifier(method.name)) | set(split_identifier(owner)) | set(tokenize(first))
    return line, words


def _is_property(method: FunctionInfo) -> bool:
    return any(d == "property" or d.endswith(".setter") for d in method.decorators)


def _class_info(entry: ClassEntry, index: IndexData) -> ClassInfo | None:
    record = index.files.get(entry.file_path)
    info = record.info if record is not None else None
    return next((c for c in info.classes if c.name == entry.name), None) if info else None
