"""Draft + retrieval -> GeneratedTest (code file + JSON data entries).

The LLM writes the code and the unique parts of each entry. Everything else is deterministic:
the context (whole pieces within the token budget), the entry keys (computed pytest ids), and
the entries themselves (template entry copied verbatim, unique parts swapped in).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import PurePosixPath
from typing import Any

from ticket2test.config import Settings
from ticket2test.generate.context import (
    BuiltContext,
    Piece,
    build_context,
    chains_piece,
    chunk_piece,
    template_piece,
)
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, Message
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.chunk import Chunk
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import (
    CTX_CLASS_PREFIX,
    CTX_TEST_PREFIX,
    GeneratedTest,
    GenerationResponse,
    TemplateEntryRef,
)
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub


class GenerationError(LLMError):
    """Generation can't proceed (e.g. no template test, or the draft is not usable)."""


def generate_test(
    draft: TestCaseDraft,
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    provider: str,
    model: str,
    conventions: str | None = None,
) -> GeneratedTest:
    gen = settings.generate
    chunks = {c.id: c for c in index.chunks}
    template_chunk, entry_key = _template(retrieval, chunks)
    file_name = target_file_name(draft, template_chunk)
    data_file_name = str(PurePosixPath(file_name).with_suffix(settings.index.data_file_suffix))

    context = build_generation_context(
        draft, retrieval, index, settings, template_chunk, entry_key, conventions
    )
    prompt = load_prompt(gen.prompt_version, settings.paths.prompts_dir)
    deployment = gen.deployment_decorators.get(draft.deployment_type, "")
    draft_scrub = scrub(draft.model_dump_json(indent=2))
    context_scrub = scrub(context.render())
    user = prompt.render_user(
        file_name=file_name,
        draft_json=draft_scrub.text,
        markers=_markers_text(draft, settings, template_chunk, index),
        deployment_decorator=f"@{deployment}" if deployment else "none (runs on all deployments)",
        placeholder=gen.placeholder_token,
        context=context_scrub.text,
    )
    request = LLMRequest(
        messages=(
            Message(role="system", content=prompt.system),
            Message(role="user", content=user),
        ),
        temperature=settings.llm.temperature,
        seed=settings.llm.seed,
        max_output_tokens=settings.llm.max_output_tokens,
        json_schema=strict_schema(GenerationResponse),
    )
    result = complete_structured(
        client,
        request,
        GenerationResponse,
        max_retries=settings.llm.max_retries_on_bad_json,
        context={
            CTX_TEST_PREFIX: settings.index.test_function_prefix,
            CTX_CLASS_PREFIX: settings.index.test_class_prefix,
        },
    )
    response = result.value

    code_scrub = scrub(response.code)
    template_entry = template_chunk.data_entries[entry_key]
    entries: dict[str, dict[str, Any]] = {}
    output_redactions = code_scrub.redacted
    for parts in response.entries:
        unique = {k: _scrub_json(v) for k, v in parts.parts().items()}
        output_redactions += sum(n for _, n in unique.values())
        entries[parts.test_id] = assemble_entry(
            template_entry,
            {k: v for k, (v, _) in unique.items()},
            gen.unique_entry_keys,
            gen.drop_template_keys,
        )

    return GeneratedTest(
        code=code_scrub.text,
        file_name=file_name,
        data_file_name=data_file_name,
        data_entries=entries,
        test_ids=[e.test_id for e in response.entries],
        template_entry_ref=TemplateEntryRef(chunk_id=template_chunk.id, entry_key=entry_key),
        ticket_id=draft.ticket_id,
        draft_ref=draft.id,
        retrieved_chunk_ids=context.chunk_ids,
        prompt_version=prompt.version,
        provider=provider,
        model=model,
        attempts=result.attempts,
        context_tokens=context.tokens,
        redactions=draft_scrub.redacted + context_scrub.redacted + output_redactions,
        notes=response.notes,
    )


# --- deterministic parts --------------------------------------------------------------------


def assemble_entry(
    template: dict[str, Any],
    unique: dict[str, Any],
    unique_keys: list[str],
    drop_keys: list[str],
) -> dict[str, Any]:
    """New entry = the template entry with its unique parts replaced.

    Shared blocks (e.g. ``config``) are deep-copied unchanged, in the template's key order.
    Per-entry overrides (``drop_keys``) are not inherited.
    """
    entry: dict[str, Any] = {}
    for key, value in template.items():
        if key in drop_keys:
            continue
        entry[key] = (
            copy.deepcopy(unique[key])
            if key in unique_keys and key in unique
            else copy.deepcopy(value)
        )
    for key in unique_keys:
        if key not in entry and key in unique:
            entry[key] = copy.deepcopy(unique[key])
    return entry


def target_file_name(draft: TestCaseDraft, template: Chunk) -> str:
    """``<template's folder>/test_<ticket>.py`` (repo-relative; only written to the output dir)."""
    slug = re.sub(r"[^a-z0-9]+", "_", draft.ticket_id.lower()).strip("_") or "ticket"
    folder = PurePosixPath(template.file_path).parent
    return str(folder / f"test_{slug}.py")


def build_generation_context(
    draft: TestCaseDraft,
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    template_chunk: Chunk,
    entry_key: str,
    conventions: str | None = None,
) -> BuiltContext:
    chunks = {c.id: c for c in index.chunks}
    catalog = index.catalog
    pieces: list[Piece] = []
    if conventions:
        pieces.append(Piece("Team conventions for tests", conventions, required=True))
    pieces.append(template_piece(template_chunk, entry_key))

    # The base test class (and its in-repo bases), so inherited helpers are visible.
    used: set[str] = {template_chunk.id}
    test_class = catalog.class_named(template_chunk.class_name or "")
    if test_class is not None:
        for base in catalog.mro(test_class.qualname)[1:]:
            chunk = chunks.get(f"{base.file_path}::{base.name}")
            if chunk is not None and chunk.id not in used:
                full = _whole_class(chunk, index)
                pieces.append(
                    Piece(
                        f"Base class: {base.name} ({base.file_path})",
                        f"```python\n{full}\n```",
                        chunk.id,
                    )
                )
                used.add(chunk.id)

    hits = [chunks[h.chunk_id] for h in retrieval.hits if h.chunk_id in chunks]
    examples = [c for c in hits if c.kind == "test" and c.id not in used][
        : settings.generate.max_example_tests
    ]
    for chunk in examples:
        pieces.append(chunk_piece(chunk, "Similar test"))
        used.add(chunk.id)

    page_objects = _page_objects_for(template_chunk, examples, hits, index)
    chains = chains_piece(catalog, [q for q, _ in page_objects])
    if chains is not None:
        pieces.append(chains)
    for _, chunk in page_objects:
        if chunk.id not in used:
            pieces.append(chunk_piece(chunk, "Page object"))
            used.add(chunk.id)

    for chunk in hits:
        if chunk.id not in used:
            pieces.append(chunk_piece(chunk, "Related code"))
            used.add(chunk.id)

    return build_context(pieces, settings.context.max_tokens, settings.context.chars_per_token)


def _template(retrieval: RetrievalResult, chunks: dict[str, Chunk]) -> tuple[Chunk, str]:
    for ref in retrieval.templates:
        chunk = chunks.get(ref.chunk_id)
        if chunk is not None and ref.entry_key in chunk.data_entries:
            return chunk, ref.entry_key
    raise GenerationError(
        "no template test with a JSON data entry was retrieved; run `retrieve` against an "
        "indexed suite that has data files"
    )


def _whole_class(header_chunk: Chunk, index: IndexData) -> str:
    """A class's full source (the class chunk itself is header-only unless it's a page object)."""
    record = index.files.get(header_chunk.file_path)
    if record is not None and record.info is not None:
        for cls in record.info.classes:
            if cls.name == header_chunk.symbol_name:
                return cls.code
    return header_chunk.code


def _page_objects_for(
    template: Chunk, examples: list[Chunk], hits: list[Chunk], index: IndexData
) -> list[tuple[str, Chunk]]:
    """Page objects reached by the template's and examples' chains, then any page-object hits."""
    catalog = index.catalog
    chunks = {c.id: c for c in index.chunks}
    found: dict[str, Chunk] = {}
    for test in [template, *examples]:
        for steps in test.refs.self_chains:
            if test.class_name is None:
                continue
            for qualname in catalog.resolve_chain(test.class_name, steps).types:
                entry = catalog.classes.get(qualname) if qualname else None
                if entry is not None and qualname in catalog.page_objects:
                    chunk = chunks.get(f"{entry.file_path}::{entry.name}")
                    if chunk is not None:
                        found.setdefault(qualname, chunk)
    for chunk in hits:
        if chunk.kind == "page_object":
            qualname = next(
                (q for q, e in catalog.classes.items() if f"{e.file_path}::{e.name}" == chunk.id),
                None,
            )
            if qualname:
                found.setdefault(qualname, chunk)
    return list(found.items())


def marker_values(
    draft: TestCaseDraft, settings: Settings, template: Chunk, index: IndexData
) -> dict[str, str]:
    """Marker values for the new test. Component and suite must be values the suite already
    uses: the draft's value if it matches one, else the template test's value."""

    def template_value(name: str) -> str | None:
        return next((str(m.args[0]) for m in template.markers if m.name == name and m.args), None)

    known = index.catalog.markers
    values = {"priority": draft.markers.priority, "project": settings.markers.project}
    for name, drafted in (("component", draft.markers.component), ("suite", draft.markers.suite)):
        match = next((v for v in known.get(name, []) if v.lower() == drafted.lower()), None)
        chosen = match or template_value(name)
        if chosen:
            values[name] = chosen
    return values


def _markers_text(
    draft: TestCaseDraft, settings: Settings, template: Chunk, index: IndexData
) -> str:
    values = marker_values(draft, settings, template, index)
    return ", ".join(f'@pytest.mark.{k}("{v}")' for k, v in values.items())


def _scrub_json(value: dict[str, Any]) -> tuple[dict[str, Any], int]:
    result = scrub(json.dumps(value))
    if not result.redacted:
        return value, 0
    cleaned: dict[str, Any] = json.loads(result.text)
    return cleaned, result.redacted


__all__ = [
    "GenerationError",
    "assemble_entry",
    "build_generation_context",
    "generate_test",
    "target_file_name",
]
