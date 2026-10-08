"""Draft + retrieval -> GeneratedTest (code file + JSON data entries).

The LLM writes the code and, per data entry, a plan: which sections of the base entry (the
template test's entry) to keep and which values to change. Everything else is deterministic:
the context (whole pieces within the token budget), the pytest ids, building the entries from
the base entry, re-labelling, and formatting code and data to the suite's style rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
from ticket2test.generate.entries import build_entry
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.masking import masker_of
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.chunk import Chunk, DataFormat
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import (
    CTX_BASE_ENTRY,
    CTX_BASE_ID,
    CTX_CLASS_PREFIX,
    CTX_DATA_ACCESS,
    CTX_EXPECTATIONS,
    CTX_ID_FIELD,
    CTX_PER_ENTRY_KEYS,
    CTX_SEED_SECTIONS,
    CTX_TEST_PREFIX,
    CTX_TICKET_ID,
    GeneratedTest,
    GenerationResponse,
    TemplateEntryRef,
)
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub
from ticket2test.security.masking import Masker
from ticket2test.style import FormatError, format_json, format_python


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
    setup = prepare_generation(draft, retrieval, index, settings, conventions)
    result = complete_structured(
        client,
        setup.request,
        GenerationResponse,
        max_retries=settings.llm.max_retries_on_bad_json,
        context=setup.validation_context,
    )
    return assemble(setup, result.value, result.attempts, provider, model, masker_of(client))


@dataclass(frozen=True)
class GenerationSetup:
    """Everything one generation conversation needs, built before the first LLM call."""

    draft: TestCaseDraft
    settings: Settings
    index: IndexData
    request: LLMRequest
    validation_context: dict[str, Any]
    template_chunk: Chunk
    entry_key: str
    base_entry: dict[str, Any]
    layout: DataFormat
    context: BuiltContext
    prompt_version: str
    input_redactions: int


def prepare_generation(
    draft: TestCaseDraft,
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    conventions: str | None = None,
) -> GenerationSetup:
    gen, data = settings.generate, settings.data
    chunks = {c.id: c for c in index.chunks}
    template_chunk, entry_key = _template(retrieval, chunks)
    base_entry = template_chunk.data_entries[entry_key]
    layout: DataFormat = template_chunk.data_format or data.format

    context = build_generation_context(
        draft, retrieval, index, settings, template_chunk, entry_key, conventions
    )
    prompt = load_prompt(gen.prompt_version, settings.paths.prompts_dir)
    deployment = gen.deployment_decorators.get(draft.deployment_type, "")
    draft_scrub = scrub(draft.model_dump_json(indent=2))
    context_scrub = scrub(context.render())
    user = prompt.render_user(
        template_file=template_chunk.file_path,
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
        model=model_name(settings, "generate"),
    )
    return GenerationSetup(
        draft=draft,
        settings=settings,
        index=index,
        request=request,
        validation_context={
            CTX_TEST_PREFIX: settings.index.test_function_prefix,
            CTX_CLASS_PREFIX: settings.index.test_class_prefix,
            CTX_BASE_ENTRY: base_entry,
            CTX_BASE_ID: entry_key,
            CTX_ID_FIELD: data.id_field,
            CTX_PER_ENTRY_KEYS: data.per_entry_keys,
            CTX_DATA_ACCESS: data.access,
            CTX_EXPECTATIONS: data.expectation_sections,
            CTX_SEED_SECTIONS: data.seed_sections,
            CTX_TICKET_ID: draft.ticket_id,
        },
        template_chunk=template_chunk,
        entry_key=entry_key,
        base_entry=base_entry,
        layout=layout,
        context=context,
        prompt_version=prompt.version,
        input_redactions=draft_scrub.redacted + context_scrub.redacted,
    )


def assemble(
    setup: GenerationSetup,
    response: GenerationResponse,
    attempts: int,
    provider: str,
    model: str,
    masker: Masker | None = None,
) -> GeneratedTest:
    """Deterministic part after the LLM: restore masked payloads, scrub, format, build the
    entries, record traceability."""
    settings, data, gen = setup.settings, setup.settings.data, setup.settings.generate
    response = unmask_generation(response, masker)
    code_scrub = scrub(response.code)
    notes = response.notes
    try:
        code = format_python(
            code_scrub.text, settings.style.python, first_party(setup.index, settings)
        )
    except FormatError as exc:
        code = code_scrub.text
        notes = f"{notes} (not formatted: {exc})".strip()

    order = {test_id: n for n, test_id in enumerate(_ids(code, settings))}
    entries: list[dict[str, Any]] = []
    output_redactions = code_scrub.redacted
    for plan in sorted(response.entries, key=lambda p: order.get(p.test_id, len(order))):
        entry = build_entry(
            setup.base_entry,
            setup.entry_key,
            plan.test_id,
            plan.copy_sections,
            plan.change_tuples(),
            id_field=data.id_field,
            per_entry_keys=data.per_entry_keys,
            test_prefix=settings.index.test_function_prefix,
        )
        cleaned, redacted = _scrub_json(entry)
        output_redactions += redacted
        entries.append(cleaned)

    folder = PurePosixPath(setup.template_chunk.file_path).parent
    file_name = str(folder / f"{response.module_name}.py")
    checklist = list(dict.fromkeys([*gen.review_checklist_defaults, *response.review_checklist]))
    return GeneratedTest(
        code=code,
        file_name=file_name,
        data_file_name=str(PurePosixPath(file_name).with_suffix(settings.index.data_file_suffix)),
        data_entries=entries,
        data_format=setup.layout,
        test_ids=list(order),
        template_entry_ref=TemplateEntryRef(
            chunk_id=setup.template_chunk.id, entry_key=setup.entry_key
        ),
        ticket_id=setup.draft.ticket_id,
        draft_ref=setup.draft.id,
        retrieved_chunk_ids=setup.context.chunk_ids,
        prompt_version=setup.prompt_version,
        provider=provider,
        model=model,
        attempts=attempts,
        context_tokens=setup.context.tokens,
        redactions=setup.input_redactions + output_redactions,
        notes=notes,
        review_checklist=checklist,
        entry_plans=list(response.entries),
    )


# --- deterministic parts --------------------------------------------------------------------


def unmask_generation(response: GenerationResponse, masker: Masker | None) -> GenerationResponse:
    """Put masked payloads back: in code string literals, in JSON values, in plain text."""
    if masker is None:
        return response
    plans = [
        plan.model_copy(
            update={
                "changes": [
                    change.model_copy(
                        update={"value_json": masker.unmask_json_text(change.value_json)}
                    )
                    for change in plan.changes
                ]
            }
        )
        for plan in response.entries
    ]
    return response.model_copy(
        update={
            "code": masker.unmask_code(response.code),
            "entries": plans,
            "review_checklist": [masker.unmask(item) for item in response.review_checklist],
            "notes": masker.unmask(response.notes),
        }
    )


def first_party(index: IndexData, settings: Settings) -> list[str]:
    """Import-sorting roots: configured, else the target repo's top-level packages."""
    if settings.style.python.first_party:
        return list(settings.style.python.first_party)
    roots = {
        record.info.module.split(".", 1)[0]
        for record in index.files.values()
        if record.info is not None and "." in record.info.module
    }
    return sorted(roots)


def class_scaffold(chunk: Chunk, index: IndexData, methods: list[str] | None = None) -> str | None:
    """The template module's imports, its class decorators and class line, and the class's
    setup/teardown methods (``methods``), as written."""
    record = index.files.get(chunk.file_path)
    if record is None or record.info is None or chunk.class_name is None:
        return None
    cls = next((c for c in record.info.classes if c.name == chunk.class_name), None)
    if cls is None:
        return None
    bases = f"({', '.join(cls.bases)})" if cls.bases else ""
    header = [*(f"@{d}" for d in cls.decorators), f"class {cls.name}{bases}:"]
    imports = [*record.info.imports, ""] if record.info.imports else []
    hooks = [m for m in cls.methods if m.name in (methods or [])]
    body = ["\n\n".join(_as_in_class(m.code, cls.code) for m in hooks)] if hooks else []
    return "\n".join([*imports, *header, *body])


def _as_in_class(method_code: str, class_code: str) -> str:
    """Extracted method code starts at its first character; restore the first line's indent
    from the class source (the other lines keep theirs)."""
    first = method_code.split("\n", 1)[0]
    for line in class_code.split("\n"):
        if line.strip() == first.strip():
            return line[: len(line) - len(line.lstrip())] + method_code
    return method_code


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
    entry_json = format_json(template_chunk.data_entries[entry_key], settings.style.json_files)
    pieces.append(
        template_piece(
            template_chunk,
            entry_key,
            entry_json,
            class_scaffold(template_chunk, index, settings.generate.scaffold_methods),
        )
    )

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


def _ids(code: str, settings: Settings) -> list[str]:
    from ticket2test.generate.inspect import computed_test_ids

    return computed_test_ids(
        code, settings.index.test_function_prefix, settings.index.test_class_prefix
    )


__all__ = [
    "GenerationError",
    "build_generation_context",
    "class_scaffold",
    "first_party",
    "generate_test",
]
