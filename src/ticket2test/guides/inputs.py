"""What the guide model is shown for one area. Picked by code, within a token cap.

The model doesn't explore: it gets the area summary and the code the area's tests rely on most,
in this order, until ``guides.max_input_tokens`` is reached. A piece that doesn't fit is
skipped whole (never cut mid-function).

1. the area summary (always)
2. the typical tests, each with one of its data entries
3. the test classes' scaffold (class header and setup/teardown methods)
4. the page objects the area's chains reach, most used first
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
        scaffold = [found.header_code] + [
            m.code for m in found.methods if m.name in settings.generate.scaffold_methods
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
            if chunk_id in chunks:
                add(f"Page object {chunk_id}", _code(chunks[chunk_id].code))

    for helper in area.base_helpers:
        for chunk in index.chunks:
            if chunk.symbol_name == helper.name and chunk.kind != "test" and "." in chunk.qualname:
                add(f"Helper {chunk.id}", _code(chunk.code))
                break

    return Material(text="\n".join(blocks), pieces=pieces, skipped=skipped, tokens=used)


def _code(code: str) -> str:
    return scrub_code(code).text
