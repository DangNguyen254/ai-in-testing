"""What the guide model is shown for one area. Picked by code, within a token cap.

The model doesn't explore: it gets the area summary and the code the area's tests rely on most,
in this order, until ``guides.max_input_tokens`` is reached. A piece that doesn't fit is
skipped whole (never cut mid-function).

1. the area summary (always)
2. the typical tests, each with one of its data entries
3. the test classes' scaffold (class header, setup/teardown and the class's own helper methods)
4. the page objects the area's chains reach, most used first; a page object larger than
   ``guides.max_piece_tokens`` (real page modules run to tens of thousands of lines) goes in as
   an outline: its members with types and signatures, the ones this area uses first
5. the base-class helper methods the tests call
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ticket2test.config import Settings
from ticket2test.generate.context import estimate_tokens
from ticket2test.index.indexer import IndexData
from ticket2test.models.suite_map import AreaSummary
from ticket2test.security import scrub_code, scrub_text
from ticket2test.suitemap.render import render_area


@dataclass(frozen=True)
class Material:
    text: str  # what goes into the prompt
    pieces: list[str]  # labels of what was included, for traceability
    skipped: list[str]  # labels that didn't fit
    tokens: int  # estimate


def pick_material(area: AreaSummary, index: IndexData, settings: Settings) -> Material:
    cpt = settings.context.chars_per_token
    budget = settings.guides.max_input_tokens
    chunks = {c.id: c for c in index.chunks}
    blocks: list[str] = []
    pieces: list[str] = []
    skipped: list[str] = []
    used = 0

    def add(label: str, body: str, required: bool = False) -> None:
        nonlocal used
        block = f"### {label}\n{body.rstrip()}\n"
        cost = estimate_tokens(block, cpt)
        if not required and used + cost > budget:
            skipped.append(label)
            return
        blocks.append(block)
        pieces.append(label)
        used += cost

    add("Area summary (built by code from the index)", scrub_text(render_area(area)), True)

    for chunk_id in area.examples:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        body = _code(chunk.code)
        entry = next(iter(chunk.data_entries.values()), None)
        if entry is not None:
            data = json.dumps(entry, indent=1, ensure_ascii=False)
            body += f"\n\nOne of its data entries ({chunk.data_file}):\n{scrub_text(data)}"
        add(f"Typical test {chunk_id}", body)

    for cls in area.classes:
        info = index.files[cls.file_path].info
        found = next((c for c in info.classes if c.name == cls.name), None) if info else None
        if found is None:
            continue
        prefix = settings.index.test_function_prefix
        scaffold = [found.header_code] + [  # setup/teardown and helpers such as _add_item()
            m.code for m in found.methods if not m.name.startswith(prefix)
        ]
        add(f"Test class scaffold {cls.file_path}::{cls.name}", _code("\n\n".join(scaffold)))

    catalog = index.catalog
    seen: set[str] = set()
    for chain in area.chains:
        resolution = catalog.resolve_chain_from_roots(chain.name)
        for qualname in resolution.types:
            entry_class = catalog.classes.get(qualname) if qualname else None
            if entry_class is None or qualname in seen or qualname not in catalog.page_objects:
                continue
            seen.add(qualname)
            chunk_id = f"{entry_class.file_path}::{entry_class.name}"
            if chunk_id not in chunks:
                continue
            code = _code(chunks[chunk_id].code)
            if estimate_tokens(code, cpt) <= settings.guides.max_piece_tokens:
                add(f"Page object {chunk_id}", code)
            else:
                area_names = {a.name for a in area.page_actions} | {
                    step for c in area.chains for step in c.name.split(".")
                }
                add(f"Page object {chunk_id} (outline)", _outline(qualname, index, area_names))

    for helper in area.base_helpers:
        for chunk in index.chunks:
            if chunk.symbol_name == helper.name and chunk.kind != "test" and "." in chunk.qualname:
                add(f"Helper {chunk.id}", _code(chunk.code))
                break

    return Material(text="\n".join(blocks), pieces=pieces, skipped=skipped, tokens=used)


def _outline(qualname: str, index: IndexData, used: set[str], limit: int = 80) -> str:
    """A large class as its member list: properties/attributes with their types, method
    signatures (first line of each def); members the area uses first."""
    catalog = index.catalog
    entry = catalog.classes[qualname]
    info = index.files[entry.file_path].info
    found = next((c for c in info.classes if c.name == entry.name), None) if info else None
    signatures = {m.name: m.code.strip().splitlines()[0] for m in found.methods} if found else {}
    rows: list[tuple[bool, str]] = []
    for name, (defined_in, member) in sorted(catalog.members_of(qualname).items()):
        if name.startswith("_") or (member.kind == "attribute" and name.isupper()):
            continue
        if member.kind == "method":
            line = signatures.get(name, f"def {name}(...)")
        else:
            kind = "property" if member.kind == "property" else "attribute"
            line = f"{name}: {kind}{f' -> {member.type_text}' if member.type_text else ''}"
        if defined_in.qualname != qualname:
            line += f"  (from {defined_in.name})"
        rows.append((name in used, line))
    ordered = [line for flag, line in rows if flag] + [line for flag, line in rows if not flag]
    head = f"class {entry.name}({', '.join(entry.bases)})  # {len(rows)} public members"
    shown = ordered[:limit]
    more = [f"... and {len(ordered) - limit} more"] if len(ordered) > limit else []
    return "\n".join([head, *(f"    {line}" for line in shown), *more])


def _code(code: str) -> str:
    return scrub_code(code).text
