"""Draft + retrieval -> GeneratedTest (code file + JSON data entries).

The LLM writes the code and, per data entry, a plan: which sections of the base entry (the
template test's entry) to keep and which values to change. Everything else is deterministic:
the context (whole pieces within the token budget), the pytest ids, building the entries from
the base entry, re-labelling, and formatting code and data to the suite's style rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
from ticket2test.generate.conventions import Conventions, convention_sections, with_conventions
from ticket2test.generate.entries import build_entry, function_of
from ticket2test.generate.inspect import data_use
from ticket2test.index.catalog import SymbolCatalog
from ticket2test.index.datafile import function_data_path, layout_of, module_data_path
from ticket2test.index.extract import ClassInfo, module_name
from ticket2test.index.indexer import IndexData
from ticket2test.knowledge.vocabulary import entry_values, render_entry_values
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
    CTX_CONVENTION_KEYS,
    CTX_DATA_ACCESS,
    CTX_EXPECTATION_SETS,
    CTX_EXPECTATIONS,
    CTX_ID_FIELD,
    CTX_INHERITED_IDS,
    CTX_PER_ENTRY_KEYS,
    CTX_SEED_SECTIONS,
    CTX_TEST_PREFIX,
    CTX_TICKET_ID,
    EntryPlan,
    GeneratedTest,
    GenerationResponse,
    TemplateEntryRef,
    unconsumed_keys,
)
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub, scrub_code
from ticket2test.security.masking import Masker
from ticket2test.style import FormatError, format_json, format_python
from ticket2test.style.local import detect_python_style


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
    conventions: Conventions = field(default_factory=Conventions)  # sections every entry has


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

    conventions_ = convention_sections(template_chunk.file_path, index, settings)
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
            CTX_EXPECTATIONS: data.section_helpers(),
            CTX_EXPECTATION_SETS: data.allowed_expectation_sets,
            CTX_SEED_SECTIONS: data.seed_sections,
            CTX_CONVENTION_KEYS: conventions_.keys,
            CTX_TICKET_ID: draft.ticket_id,
            CTX_INHERITED_IDS: [
                i for c in _inherited_chunks(template_chunk, index) for i in c.test_ids
            ],
        },
        template_chunk=template_chunk,
        entry_key=entry_key,
        base_entry=base_entry,
        layout=layout,
        context=context,
        conventions=conventions_,
        prompt_version=prompt.version,
        input_redactions=draft_scrub.redacted + context_scrub.redacted,
    )


# A new module only: dropped when the method is spliced into the template's own class.
SCAFFOLD_COPY_NOTE = "The new class is a copy of "


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
    code_scrub = scrub_code(response.code)  # literals and comments only: code stays valid
    notes = response.notes
    style = settings.style.python
    if settings.style.follow_local:  # cosmetic rules follow the area: the template's style
        style = detect_python_style(setup.template_chunk.code, style)
    try:
        code = format_python(code_scrub.text, style, first_party(setup.index, settings))
    except FormatError as exc:
        code = code_scrub.text
        notes = f"{notes} (not formatted: {exc})".strip()

    code, shell_note, shell_helpers = with_template_shell(code, setup)
    try:
        order = {test_id: n for n, test_id in enumerate(_ids(code, settings))}
    except ValueError as exc:  # the LLM's code parsed; a step in code broke it: a bug to report
        raise GenerationError(
            f"generated code broken after restoring and formatting: {exc}"
        ) from exc
    plans, fixes = rekey_plans(list(response.entries), code, setup)
    fixes += [shell_note] if shell_note else []
    entries: list[dict[str, Any]] = []
    conventional: set[str] = set()  # convention sections the plans left out, added by code
    output_redactions = code_scrub.redacted
    for plan in sorted(plans, key=lambda p: order.get(p.test_id, len(order))):
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
        entry, copied = with_conventions(entry, setup.base_entry, setup.conventions)
        conventional.update(copied)
        entry, removed = strip_unread(entry, code, setup)
        fixes += removed
        cleaned, redacted = _scrub_json(entry)
        output_redactions += redacted
        entries.append(cleaned)
    entries, inherited_ids, added = with_inherited_entries(code, entries, setup)
    fixes += added
    if fixes:
        notes = f"{notes} Fixed in code: {'; '.join(fixes)}.".strip()

    folder = PurePosixPath(setup.template_chunk.file_path).parent
    file_name = str(folder / f"{response.module_name}.py")
    checklist = list(dict.fromkeys([*gen.review_checklist_defaults, *response.review_checklist]))
    if shell_helpers:
        checklist.append(
            f"{SCAFFOLD_COPY_NOTE}{setup.template_chunk.class_name}'s scaffold, not a "
            f"subclass, so its own methods {', '.join(shell_helpers)} were copied in too. "
            "Consider a shared base class for them instead of the copy."
        )
    if conventional:  # the plans left them out: say what code added (copied by the model: no note)
        checklist.append(
            f"Every entry in {setup.conventions.scope} has "
            f"{', '.join(setup.conventions.keys)}: the new entries carry them too (added by "
            f"code: {', '.join(sorted(conventional))}), with the base entry's values (or the "
            "nearest sibling's). Confirm the values fit this test."
        )
    data_file_name = module_data_path(file_name, settings.index)
    tpl = setup.template_chunk
    if order and layout_of(tpl.file_path, tpl.symbol_name, tpl.data_file, settings.index) == (
        "function"
    ):  # the area keeps one data file per test: name it after the (first) test
        functions = list(dict.fromkeys(function_of(i) for i in order))
        data_file_name = function_data_path(file_name, functions[0], settings.index)
        if len(functions) > 1:
            checklist.append(
                f"This area keeps one data file per test: split the entries of "
                f"{', '.join(functions[1:])} out of {data_file_name}."
            )
    return GeneratedTest(
        code=code,
        file_name=file_name,
        data_file_name=data_file_name,
        data_entries=entries,
        data_format=setup.layout,
        test_ids=[*order, *(i for i in inherited_ids if i not in order)],
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
        entry_plans=plans,
    )


def with_template_shell(code: str, setup: GenerationSetup) -> tuple[str, str, list[str]]:
    """The generated module rebuilt on the template class's shell, in code: the template
    module's imports, the class's decorator stack, base class and setup/teardown, then the
    generated test methods (and only the imports they use).

    Decorators the generated class carries with the same name keep their generated arguments
    (values chosen for this draft, e.g. the component marker); decorators the template lacks
    (e.g. a deployment decorator for a cloud-only draft) are added after the stack. A module
    with other top-level code, or one that doesn't parse, is left as written.
    The template class's own methods the scaffold and the new tests call come along (a new class
    doesn't inherit it). Returns (code, note, the methods copied that way); the note is "" when
    nothing changed.
    """
    import ast

    from ticket2test.generate.patch import PatchError, splice_methods

    settings, chunk = setup.settings, setup.template_chunk
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, "", []
    # the template class's own methods the new tests call: a new class doesn't inherit them
    called = {
        name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for name in _SELF_NAME.findall(ast.get_source_segment(code, node) or "")
    }
    defined = {
        n.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for n in node.body
        if isinstance(n, ast.FunctionDef)
    }
    shell = class_scaffold(
        chunk,
        setup.index,
        settings.generate.scaffold_methods,
        also=called - defined,
        test_prefix=settings.index.test_function_prefix,
    )
    if shell is None or chunk.class_name is None:
        return code, "", []
    prefix = settings.index.test_class_prefix
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    others = [
        n
        for n in tree.body
        if not isinstance(n, ast.Import | ast.ImportFrom | ast.ClassDef)
        and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))  # docstring
    ]
    if len(classes) != 1 or not classes[0].name.startswith(prefix) or others:
        return code, "", []
    generated = classes[0]
    placeholder = "\n" + " " * settings.style.python.indent_width + "pass"
    bare = shell.rstrip().endswith(":")  # a class without setup/teardown
    if bare:  # give it a body to parse and splice into; removed again below
        shell = shell.rstrip() + placeholder
    try:
        shell_tree = ast.parse(shell)
    except SyntaxError:
        return code, "", []
    template = next(n for n in shell_tree.body if isinstance(n, ast.ClassDef))

    def name_of(node: ast.expr) -> str:
        return ast.unparse(node.func if isinstance(node, ast.Call) else node)

    ours = {name_of(d): ast.get_source_segment(code, d) or "" for d in generated.decorator_list}
    stack = []
    for decorator in template.decorator_list:
        name = name_of(decorator)
        stack.append(ours.pop(name, "") or ast.get_source_segment(shell, decorator) or "")
    stack += list(ours.values())
    lines = shell.split("\n")
    first = min([template.lineno, *(d.lineno for d in template.decorator_list)])
    class_line = lines[template.lineno - 1].replace(
        f"class {template.name}", f"class {generated.name}", 1
    )
    header = [*(f"@{d}" for d in stack), class_line]
    rebuilt = "\n".join([*lines[: first - 1], *header, *lines[template.lineno :]]).rstrip()
    doc = ast.get_docstring(tree, clean=False)
    if doc is not None:
        rebuilt = f"{ast.get_source_segment(code, tree.body[0])}\n\n{rebuilt}"
    copied = sorted(_methods_in(shell) - set(settings.generate.scaffold_methods) - defined)
    try:
        spliced, _added = splice_methods(rebuilt + "\n", generated.name, code, settings)
        if bare:
            spliced = spliced.replace(placeholder + "\n", "\n", 1)
        roots = {name_of(ast.parse(d, mode="eval").body).split(".")[0] for d in stack}
        spliced = _add_imports(spliced, code, roots)  # for decorators from the generated class
        spliced = explicit_star_imports(spliced, setup.index.catalog)
        result = format_python(spliced, settings.style.python, first_party(setup.index, settings))
    except (PatchError, SyntaxError, FormatError):
        return code, "", []
    if result == code:
        return code, "", []
    note = f"class shell (imports, decorators, base, setup) from {chunk.class_name}"
    if copied:
        note += f", with its own methods {', '.join(copied)}"
    return result, note, copied


def explicit_star_imports(code: str, catalog: SymbolCatalog) -> str:
    """``from m import *`` (copied with a template's imports) as an import of the names the code
    uses from ``m``, or nothing when it uses none. Star imports from modules outside the repo
    stay: what they bind isn't known."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    loaded = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    own = {
        (a.asname or a.name).split(".")[0]
        for n in tree.body
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in n.names
        if a.name != "*"
    } | {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.ClassDef)}
    lines = code.splitlines(keepends=True)
    for node in reversed(tree.body):
        if not (isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names)):
            continue
        names, known = catalog.star_names(node.module or "")
        if not known:
            continue
        used = sorted((names & loaded) - own)
        text = f"from {node.module} import {', '.join(used)}\n" if used else ""
        lines[node.lineno - 1 : node.end_lineno] = [text]
    return "".join(lines)


def _add_imports(target: str, source: str, names: set[str]) -> str:
    """Import statements of ``source`` that bind any of ``names`` and that ``target`` lacks."""
    import ast

    have = {
        (a.asname or a.name).split(".")[0]
        for n in ast.parse(target).body
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in n.names
    }
    missing = [
        ast.get_source_segment(source, n) or ""
        for n in ast.parse(source).body
        if isinstance(n, ast.Import | ast.ImportFrom)
        and {(a.asname or a.name).split(".")[0] for a in n.names} & (names - have)
    ]
    return "\n".join(missing) + "\n" + target if missing else target


def _inherited_chunks(template: Chunk, index: IndexData) -> list[Chunk]:
    """Tests the template class inherits (indexed as chunks of the class)."""
    return [
        c
        for c in index.chunks
        if c.kind == "test"
        and c.inherited_from
        and c.class_name == template.class_name
        and c.file_path == template.file_path
    ]


def with_inherited_entries(
    code: str, entries: list[dict[str, Any]], setup: GenerationSetup
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Entries for the tests the generated class inherits from repo base classes.

    A shared test defined in a base class (e.g. a verdict check every file-policy class runs)
    needs one entry per subclass. The LLM writes only its own tests, so the entry is copied
    here from the template class's entry for the same test (the nearest existing entry), else
    from any class's. Returns (entries, inherited ids, notes).
    """
    import ast

    from ticket2test.validate.datause import Resolver

    settings, data = setup.settings, setup.settings.data
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return entries, [], []
    module = module_name(setup.template_chunk.file_path, settings.index.import_roots)
    resolver = Resolver(
        tree,
        module,
        setup.index,
        data.access,
        set(data.helper_patterns()),
    )
    prefix = settings.index.test_class_prefix
    have = {str(e.get(data.id_field)) for e in entries}
    inherited: list[str] = []
    copied: list[dict[str, Any]] = []
    notes: list[str] = []
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        if not cls.name.startswith(prefix):
            continue
        for test in resolver.inherited_tests(cls, settings.index.test_function_prefix):
            for test_id in test.ids:
                inherited.append(test_id)
                if test_id in have:
                    continue
                found = _inherited_entry(test.name, test_id, setup)
                if found is None:
                    continue
                source, owner = found
                skip = {data.id_field, *data.per_entry_keys}
                entry = {
                    data.id_field: test_id,
                    **{k: v for k, v in source.items() if k not in skip},
                }
                copied.append(json.loads(json.dumps(entry)))  # a deep copy
                have.add(test_id)
                notes.append(f"entry for inherited {test_id} copied from {owner}")
    return [*entries, *copied], inherited, notes


def _inherited_entry(
    name: str, test_id: str, setup: GenerationSetup
) -> tuple[dict[str, Any], str] | None:
    """(entry, class it belongs to): the template class's first, then any class's."""
    template = setup.template_chunk
    candidates = sorted(
        (c for c in setup.index.chunks if c.kind == "test" and c.symbol_name == name),
        key=lambda c: (c.class_name != template.class_name, c.file_path != template.file_path),
    )
    for chunk in candidates:
        entry = chunk.data_entries.get(test_id)
        if isinstance(entry, dict):
            return entry, chunk.class_name or chunk.file_path
    return None


def rekey_plans(
    plans: list[EntryPlan], code: str, setup: GenerationSetup
) -> tuple[list[EntryPlan], list[str]]:
    """One entry labelled with an id the code doesn't produce, while exactly one test that
    reads its data has no entry: that entry is the test's (fixed here, not by the LLM)."""
    settings = setup.settings
    ids = _ids(code, settings)
    uses = _uses(code, settings)
    keys = [p.test_id for p in plans]
    extra = [k for k in keys if k not in ids]
    missing = [i for i in ids if (u := uses.get(function_of(i))) and u.reads_data and i not in keys]
    if len(extra) != 1 or len(missing) != 1:
        return plans, []
    fixed = [
        p.model_copy(update={"test_id": missing[0]}) if p.test_id == extra[0] else p for p in plans
    ]
    return fixed, [f"entry {extra[0]!r} re-keyed to {missing[0]!r}"]


def strip_unread(
    entry: dict[str, Any], code: str, setup: GenerationSetup
) -> tuple[dict[str, Any], list[str]]:
    """Remove keys the test never reads and no helper it calls consumes (rule 1).

    Reads are followed the way the validator follows them: into ``self.<method>()`` helpers,
    also in repo base classes, and through inherited tests. A test whose reads can't be
    resolved (not found in the code) is left alone: removing keys there is a guess.
    """
    test_id = str(entry.get(setup.settings.data.id_field, ""))
    use = resolved_uses(code, setup).get(function_of(test_id))
    if use is None:
        return entry, []
    unread, _conflict = unconsumed_keys(entry, use, setup.validation_context)
    if not unread:
        return entry, []
    kept = {k: v for k, v in entry.items() if k not in unread}
    return kept, [f"removed unread {sorted(unread)} from {test_id}"]


def resolved_uses(code: str, setup: GenerationSetup) -> dict[str, Any]:
    """Data use per test name (own and inherited), following helpers into repo base classes."""
    import ast

    from ticket2test.validate.datause import Resolver

    settings, data = setup.settings, setup.settings.data
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    uses = dict(_uses(code, settings))  # module-level tests and the plain reading
    module = module_name(setup.template_chunk.file_path, settings.index.import_roots)
    resolver = Resolver(
        tree,
        module,
        setup.index,
        data.access,
        set(data.helper_patterns()),
    )
    prefix = settings.index.test_function_prefix
    for cls in resolver.classes():
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef) and fn.name.startswith(prefix):
                uses[fn.name] = resolver.data_use(cls, fn, settings.generate.scaffold_methods)
        for test in resolver.inherited_tests(cls, prefix):
            method = resolver.method(cls, test.name)
            if method is not None:
                uses[test.name] = resolver.data_use(cls, method, settings.generate.scaffold_methods)
    return uses


def _uses(code: str, settings: Settings) -> dict[str, Any]:
    data = settings.data
    return dict(
        data_use(
            code,
            data.access,
            data.helper_patterns(),
            settings.index.test_function_prefix,
        )
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


def class_scaffold(
    chunk: Chunk,
    index: IndexData,
    methods: list[str] | None = None,
    also: set[str] | None = None,
    test_prefix: str = "test",
) -> str | None:
    """The template module's imports, its class decorators and class line, and the class's
    setup/teardown methods (``methods``), as written. With them come the class's own methods
    they call (``self.<name>``, also through each other), and those named in ``also``: a new
    class copied from this one doesn't inherit it, so its own helpers would be missing."""
    record = index.files.get(chunk.file_path)
    if record is None or record.info is None or chunk.class_name is None:
        return None
    cls = next((c for c in record.info.classes if c.name == chunk.class_name), None)
    if cls is None:
        return None
    bases = f"({', '.join(cls.bases)})" if cls.bases else ""
    header = [*(f"@{d}" for d in cls.decorators), f"class {cls.name}{bases}:"]
    imports = [*record.info.imports, ""] if record.info.imports else []
    names = class_own_helpers(cls, set(methods or []) | (also or set()), test_prefix)
    picked = [m for m in cls.methods if m.name in names]  # in the class's own order
    body = ["\n\n".join(_as_in_class(m.code, cls.code) for m in picked)] if picked else []
    return "\n".join([*imports, *header, *body])


_SELF_NAME = re.compile(r"\bself\.(\w+)")


def _methods_in(source: str) -> set[str]:
    """Names of the methods of the classes in ``source`` (the scaffold)."""
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    return {
        n.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for n in node.body
        if isinstance(n, ast.FunctionDef)
    }


def class_own_helpers(cls: ClassInfo, wanted: set[str], test_prefix: str = "test") -> set[str]:
    """``wanted`` methods of the class, and the class's own non-test methods they reach
    through ``self.<name>`` (properties too), transitively."""
    own = {m.name: m for m in cls.methods}
    found: set[str] = set()
    queue = [n for n in wanted if n in own]
    while queue:
        name = queue.pop()
        if name in found:
            continue
        found.add(name)
        for used in _SELF_NAME.findall(own[name].code):
            if used in own and used not in found and not used.startswith(test_prefix):
                queue.append(used)
    return found


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

    known = entry_values(template_chunk, template_chunk.data_entries[entry_key], index, settings)
    if known:  # the suite's own values, so a changed field gets one of them, not a guess
        pieces.append(
            Piece(
                "Known values in this area for the template entry's keys",
                "Values the data of the tests in this folder uses for these keys. When the "
                "test's case refers to one of them, use the suite's value exactly; don't invent "
                "other values.\n" + render_entry_values(known),
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
    priority = draft.markers.priority
    if settings.markers.priority_from == "neighbours":
        priority = neighbour_priority(template, index) or priority
    values = {"priority": priority, "project": settings.markers.project}
    for name, drafted in (("component", draft.markers.component), ("suite", draft.markers.suite)):
        match = next((v for v in known.get(name, []) if v.lower() == drafted.lower()), None)
        chosen = match or template_value(name)
        if chosen:
            values[name] = chosen
    return values


def neighbour_priority(template: Chunk, index: IndexData) -> str | None:
    """The priority most tests next to the template use: in its class, else its file, else its
    folder (ties: the first found)."""
    folder = str(PurePosixPath(template.file_path).parent)
    tests = [c for c in index.chunks if c.kind == "test" and not c.inherited_from]
    scopes = [
        [
            c
            for c in tests
            if c.file_path == template.file_path and c.class_name == template.class_name
        ],
        [c for c in tests if c.file_path == template.file_path],
        [c for c in tests if str(PurePosixPath(c.file_path).parent) == folder],
    ]
    for scope in scopes:
        counts: dict[str, int] = {}
        for chunk in scope:
            value = next(
                (str(m.args[0]) for m in chunk.markers if m.name == "priority" and m.args), None
            )
            if value:
                counts[value] = counts.get(value, 0) + 1
        if counts:
            return max(counts, key=lambda v: counts[v])
    return None


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
