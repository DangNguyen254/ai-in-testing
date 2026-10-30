"""The framework guide: one guide for what every area shares, read next to each area's guide.

An area guide explains one feature folder; the framework under it (the base test classes, the
helpers several areas call, the fixtures, the data loader and its placeholders) is the same for
all of them, so it gets one guide of its own, built like an area guide (``guides`` step, budget,
name check) from material picked by code, in this order, within
``guides.framework_max_input_tokens``:

1. a suite overview built by code: base classes and how many test classes use them, chain
   roots and the top page areas, the helpers shared across areas, marker values, and how the
   data works (id field, access, seed and expectation sections with their helpers, the
   placeholders entries use, per-entry keys)
2. the base classes, most used first, with their in-repo bases: whole when small, else an
   outline (members with signatures), the shared helpers first
3. the shared helpers' code, most areas first: what they take, check and return
4. the fixtures the tests use most

Stored as the guide ``_framework``; its digest covers every file it was built from.
"""

from __future__ import annotations

import hashlib
from collections import Counter

from ticket2test.config import Settings
from ticket2test.generate.context import estimate_tokens
from ticket2test.guides.inputs import Material, class_outline
from ticket2test.index.catalog import ClassEntry
from ticket2test.index.indexer import IndexData
from ticket2test.models.suite_map import SuiteMap
from ticket2test.security import scrub_code, scrub_text

FRAMEWORK = "_framework"  # the stored guide's name (no area is named like this)
_MAX_BASES = 8
_MAX_FIXTURES = 10
_MAX_LISTED = 30


def framework_material(
    suite_map: SuiteMap, index: IndexData, settings: Settings
) -> tuple[Material, dict[str, str]]:
    """(the material, path -> sha256 of every file it was built from)."""
    cpt = settings.context.chars_per_token
    budget = settings.guides.framework_max_input_tokens
    catalog = index.catalog
    blocks: list[str] = []
    pieces: list[str] = []
    skipped: list[str] = []
    files: set[str] = set()
    used = 0

    def add(label: str, body: str, path: str | None = None, required: bool = False) -> None:
        nonlocal used
        block = f"### {label}\n{body.rstrip()}\n"
        cost = estimate_tokens(block, cpt)
        if not required and used + cost > budget:
            skipped.append(label)
            return
        blocks.append(block)
        pieces.append(label)
        used += cost
        if path:
            files.add(path)

    add("Suite overview (built by code from the index)", _overview(suite_map, settings), None, True)

    shared = [c.name.rsplit(".", 1)[-1] for c in suite_map.overview.shared_helpers]
    bases: list[ClassEntry] = []
    for count in suite_map.overview.base_classes[:_MAX_BASES]:
        entry = catalog.classes.get(count.name) or catalog.class_named(count.name.split(".")[-1])
        if entry is None:
            continue
        for base in catalog.mro(entry.qualname):
            if base.qualname not in {b.qualname for b in bases}:
                bases.append(base)
    for base in bases:
        chunk_id = f"{base.file_path}::{base.name}"
        info = index.files[base.file_path].info if base.file_path in index.files else None
        cls = next((c for c in info.classes if c.name == base.name), None) if info else None
        if cls is None:
            continue
        code = scrub_code(cls.code).text
        if estimate_tokens(code, cpt) <= settings.guides.max_piece_tokens:
            add(f"Base class {chunk_id}", f"```python\n{code}\n```", base.file_path)
        else:
            outline = class_outline(base.qualname, index, set(shared))
            add(f"Base class {chunk_id} (outline)", outline, base.file_path)

    for name in shared:
        for base in bases:
            info = index.files[base.file_path].info if base.file_path in index.files else None
            cls = next((c for c in info.classes if c.name == base.name), None) if info else None
            method = next((m for m in cls.methods if m.name == name), None) if cls else None
            if method is not None:
                body = f"```python\n{scrub_code(method.code).text}\n```"
                add(f"Shared helper {base.name}.{name}", body, base.file_path)
                break

    fixtures: Counter[str] = Counter()
    for area in suite_map.areas:
        fixtures.update({f.name: f.count for f in area.fixtures})
    for name, _ in fixtures.most_common(_MAX_FIXTURES):
        chunk = next(
            (c for c in index.chunks if c.symbol_name == name and c.kind == "function"), None
        )
        if chunk is not None:
            body = f"```python\n{scrub_code(chunk.code).text}\n```"
            add(f"Fixture {chunk.id}", body, chunk.file_path)

    sources = {p: index.files[p].sha256 for p in sorted(files) if p in index.files}
    material = Material(text="\n".join(blocks), pieces=pieces, skipped=skipped, tokens=used)
    return material, sources


def framework_digest(sources: dict[str, str], settings: Settings) -> str:
    """Changes when a source file changes, or when what the overview says about data does."""
    d = settings.data
    text = "\n".join(
        [f"{p} {s}" for p, s in sources.items()]
        + [d.id_field, *d.access, *d.seed_sections, *sorted(d.section_helpers())]
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _overview(suite_map: SuiteMap, settings: Settings) -> str:
    o, d = suite_map.overview, settings.data
    placeholders: Counter[str] = Counter()
    for area in suite_map.areas:
        placeholders.update({p.name: p.count for p in area.placeholders})

    def counts(items: list[tuple[str, int]]) -> str:
        return ", ".join(f"`{n}` ({c})" for n, c in items[:_MAX_LISTED]) or "(none)"

    sections = "; ".join(
        f"`{s}` read by {', '.join(f'`{h}`' for h in helpers)}"
        for s, helpers in d.section_helpers().items()
    )
    lines = [
        f"- {o.tests} tests ({o.test_ids} ids) in {o.test_classes} test classes, "
        f"{len(suite_map.areas)} areas, {o.data_entries} data entries.",
        f"- Base classes of the test classes (test classes using each): "
        f"{counts([(c.name, c.count) for c in o.base_classes])}",
        f"- Page-object roots: {', '.join(f'`{r}`' for r in o.chain_roots) or '(none)'}; "
        f"top page areas (tests): {counts([(c.name, c.count) for c in o.page_areas])}",
        f"- Helpers used in several areas (areas): "
        f"{counts([(c.name, c.count) for c in o.shared_helpers])}",
        "- Marker values: "
        + "; ".join(f"{k}: {', '.join(v[:15])}" for k, v in o.marker_values.items()),
        f"- Data: one entry per pytest id, identified by `{d.id_field}`; tests read it through "
        f"{', '.join(f'`{a}`' for a in d.access)}. Seed sections: "
        f"{', '.join(f'`{s}`' for s in d.seed_sections)}. Expectation sections: {sections}. "
        f"Per-entry keys: {', '.join(f'`{k}`' for k in d.per_entry_keys[:20])}.",
        f"- Placeholders in entry values (entries): "
        f"{counts(placeholders.most_common(_MAX_LISTED))}",
    ]
    return scrub_text("\n".join(lines))
