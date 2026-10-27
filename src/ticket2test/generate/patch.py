"""Reuse patches: a new case of an existing parametrized test, or a new method in an existing class.

The target repo is read, never written (Hard Constraint 4): a patch is the whole patched file
plus a unified diff, and both go to the output directory for the reviewer to apply.

**Variant** (code first; no LLM when the draft says enough):

1. the test has exactly one ``@pytest.mark.parametrize`` with one argument name, a literal list
   of strings, and no ``ids=``; the new value is appended to that list in place;
2. the plan (new value, base case, changed values) comes from the draft's variants: each input
   whose name equals exactly one key of the base case's entry sets that key. If an input names
   no key (or several), one small LLM call (``generate.variant_prompt``) plans the cases;
3. each new entry is a copy of the base case's entry (without per-entry overrides such as
   ``skip``) with the changes, inserted after the test's last entry; the data file is written
   in the suite's JSON style.

**Method**: the usual generator writes the test, with a template from the target class; its new
methods and the imports the file lacks are spliced into the existing class, and its entries are
appended to the existing data file.

Patched files are validated whole, and only findings the unpatched file doesn't already have
are reported, so existing debt in the suite isn't blamed on the patch.
"""

from __future__ import annotations

import ast
import copy
import difflib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ticket2test.config import Settings
from ticket2test.generate.entries import EntryError, delete_path, function_of, parse_path
from ticket2test.generate.generator import first_party
from ticket2test.generate.reuse import ReuseDecision
from ticket2test.index.datafile import function_data_path, layout_of, module_data_path
from ticket2test.index.indexer import IndexData
from ticket2test.index.tokens import split_identifier
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.masking import masker_of, unmask_model
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.chunk import Chunk, DataFormat
from ticket2test.models.draft import TestCaseDraft, Variant
from ticket2test.models.generated import (
    EntryChange,
    GeneratedTest,
    PatchedFile,
    TemplateEntryRef,
    VariantPlan,
    VariantPlanResponse,
)
from ticket2test.models.retrieval import RetrievalResult, TemplateRef
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub_text
from ticket2test.style import format_entries
from ticket2test.style.local import detect_json_style, detect_python_style, insert_entries
from ticket2test.style.python import format_python, sort_imports
from ticket2test.validate.claims import norm
from ticket2test.validate.report import Finding, ValidationReport
from ticket2test.validate.suite import read_suite_data, static_ids
from ticket2test.validate.validator import module_imports, validate_generated

CODE_PLAN = "variant_code"  # prompt_version of a variant planned without the LLM
_CASE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,20}")
_WORDS = re.compile(r"[A-Za-z][A-Za-z0-9]+")


class PatchError(ValueError):
    """The decision can't be applied as a patch (the caller falls back to a new module)."""


@dataclass(frozen=True)
class FilePatch:
    path: str  # repo-relative
    before: str
    after: str

    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                f"a/{self.path}",
                f"b/{self.path}",
            )
        )

    def record(self) -> PatchedFile:
        return PatchedFile(path=self.path, diff=self.diff())


# --- the parametrize list -----------------------------------------------------------------------


@dataclass(frozen=True)
class ParamSite:
    """Where a test's single literal parametrize list ends, and how its items are written."""

    argname: str
    values: list[str]
    end: int  # offset just after the last value
    trailing_comma: int | None  # offset just after a comma that follows it
    multiline: bool
    indent: str  # of the last value's line
    quote: str
    numeric: bool = False  # a list of whole numbers (written without quotes)

    def literal(self, case: str) -> str:
        """The new value as the list writes it; raises PatchError if it doesn't fit."""
        if not self.numeric:
            return f"{self.quote}{case}{self.quote}"
        if not case.lstrip("-").isdigit():
            raise PatchError(f"{self.argname} takes whole numbers; {case!r} isn't one")
        return str(int(case))

    def insert(self, source: str, new: list[str]) -> str:
        items = [self.literal(v) for v in new]
        if self.multiline and self.trailing_comma is not None:
            at, text = self.trailing_comma, "".join(f"\n{self.indent}{i}," for i in items)
        elif self.multiline:
            at, text = self.end, "".join(f",\n{self.indent}{i}" for i in items)
        elif self.trailing_comma is not None:
            at, text = self.trailing_comma, "".join(f" {i}," for i in items)
        else:
            at, text = self.end, "".join(f", {i}" for i in items)
        return source[:at] + text + source[at:]


def parametrize_site(source: str, class_name: str | None, function: str) -> ParamSite:
    tree = ast.parse(source)
    node = _function(tree, class_name, function)
    calls = [
        d
        for d in node.decorator_list
        if isinstance(d, ast.Call) and _dotted(d.func).endswith("parametrize")
    ]
    if len(calls) != 1:
        raise PatchError(f"{function} has {len(calls)} parametrize decorators (one is supported)")
    call = calls[0]
    if len(call.args) < 2 or any(k.arg == "ids" for k in call.keywords):
        raise PatchError(f"{function}: parametrize with ids= or keyword values is not supported")
    names, values = call.args[0], call.args[1]
    if not (isinstance(names, ast.Constant) and isinstance(names.value, str)) or "," in str(
        names.value
    ):
        raise PatchError(f"{function}: parametrize over several arguments is not supported")
    constants = [e.value for e in getattr(values, "elts", []) if isinstance(e, ast.Constant)]
    strings = all(isinstance(v, str) for v in constants)
    numbers = all(isinstance(v, int) and not isinstance(v, bool) for v in constants)
    if (
        not isinstance(values, ast.List | ast.Tuple)
        or not values.elts
        or len(constants) != len(values.elts)
        or not (strings or numbers)
    ):
        raise PatchError(
            f"{function}: parametrize values are not a literal list of strings or whole numbers"
        )
    last = values.elts[-1]
    lines = source.splitlines(keepends=True)
    end = _offset(lines, last.end_lineno or last.lineno, last.end_col_offset or 0)
    close = _offset(lines, values.end_lineno or values.lineno, values.end_col_offset or 0)
    rest = source[end:close]
    stripped = rest.lstrip()
    comma = end + len(rest) - len(stripped) + 1 if stripped.startswith(",") else None
    line = lines[last.lineno - 1]
    segment = ast.get_source_segment(source, last) or '"'
    return ParamSite(
        argname=str(names.value).strip(),
        values=[str(e.value) for e in values.elts if isinstance(e, ast.Constant)],
        end=end,
        trailing_comma=comma,
        multiline=last.lineno != values.lineno,
        indent=line[: len(line) - len(line.lstrip())],
        quote=segment[0] if segment[0] in "'\"" else '"',
        numeric=numbers and not strings,
    )


def _function(tree: ast.Module, class_name: str | None, function: str) -> ast.FunctionDef:
    body: list[ast.stmt] = tree.body
    if class_name:
        cls = next(
            (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name), None
        )
        if cls is None:
            raise PatchError(f"class {class_name} not found")
        body = cls.body
    for node in body:
        if isinstance(node, ast.FunctionDef) and node.name == function:
            return node
    raise PatchError(f"{function} not found in {class_name or 'the module'}")


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else ""


def _offset(lines: list[str], lineno: int, col_bytes: int) -> int:
    """A string offset from an ast (1-based line, UTF-8 byte column) position."""
    before = sum(len(line) for line in lines[: lineno - 1])
    return before + len(lines[lineno - 1].encode("utf-8")[:col_bytes].decode("utf-8", "ignore"))


# --- variant plans ------------------------------------------------------------------------------


def cases_of(chunk: Chunk) -> dict[str, dict[str, Any]]:
    """Parametrize value -> data entry, for a test with one parametrize."""
    prefix = chunk.symbol_name + "["
    return {
        key[len(prefix) : -1]: entry
        for key, entry in chunk.data_entries.items()
        if key.startswith(prefix) and key.endswith("]")
    }


def plan_variants_in_code(
    draft: TestCaseDraft, chunk: Chunk, site: ParamSite, settings: Settings
) -> list[VariantPlan] | None:
    """Plans from the draft's variant inputs, or None when an input names no single data key.

    A variant whose inputs the base entry already has is skipped (that case exists).
    """
    if not draft.variants:
        return None
    cases = cases_of(chunk)
    skip = {settings.data.id_field, *settings.data.per_entry_keys}
    expectations = set(settings.data.expectation_sections)
    taken = set(site.values)
    plans: list[VariantPlan] = []
    for variant in draft.variants:
        base_case = _base_case(variant, draft, site.values, cases)
        base = cases.get(base_case)
        if base is None or not variant.inputs:
            return None
        changes: list[EntryChange] = []
        for given in variant.inputs:
            found = _key_paths(base, _key(given.name), skip)
            if len(found) > 1:  # the input, plus its restatements in the expectations
                found = [f for f in found if f[0].split(".", 1)[0] not in expectations]
            if len(found) != 1:
                return None
            path, current = found[0]
            ok, value = _coerce(given.value, current)
            copies, derived = _dependents(base, path, current, expectations)
            if not ok or derived:
                return None
            if any(v == value for _, v in _leaves(base)):
                # the value selects something the entry already has (a seeded file): its old
                # copies in seed sections are other objects; only the expectations follow
                copies = [c for c in copies if c.split(".", 1)[0] in expectations]
            if value != current:
                changes += [
                    EntryChange(op="set", path=p, value_json=json.dumps(value, ensure_ascii=False))
                    for p in [path, *copies]
                ]
        if not changes:
            continue
        case = _case_from_argument(variant, site) or _case_name(variant, taken)
        if case in taken:
            continue  # the case exists already: nothing new to add
        taken.add(case)
        plans.append(
            VariantPlan(
                case=case,
                base_case=base_case,
                changes=changes,
                notes=(
                    "Planned in code from the draft's inputs: values that must stay consistent "
                    "with them (e.g. content a new pattern must match) are unchanged; check them."
                ),
            )
        )
    return plans


def plan_variants_with_llm(
    draft: TestCaseDraft, chunk: Chunk, site: ParamSite, settings: Settings, client: LLMClient
) -> tuple[list[VariantPlan], int, str]:
    prompt = load_prompt(settings.generate.variant_prompt, settings.paths.prompts_dir)
    entries = [chunk.data_entries[k] for k in chunk.test_ids if k in chunk.data_entries]
    user = prompt.render_user(
        test_file=chunk.file_path,
        argname=site.argname,
        existing_values=", ".join(site.values),
        test_code=scrub_text(chunk.code),
        entries_json=scrub_text(json.dumps(entries, indent=2, ensure_ascii=False)),
        draft_json=scrub_text(draft.model_dump_json(indent=2)),
    )
    request = LLMRequest(
        messages=(
            Message(role="system", content=prompt.system),
            Message(role="user", content=user),
        ),
        temperature=settings.llm.temperature,
        seed=settings.llm.seed,
        max_output_tokens=min(settings.llm.max_output_tokens, 4000),
        json_schema=strict_schema(VariantPlanResponse),
        model=model_name(settings, "variant_plan"),
    )
    result = complete_structured(
        client, request, VariantPlanResponse, settings.llm.max_retries_on_bad_json
    )
    value = unmask_model(result.value, masker_of(client))
    return list(value.variants), result.attempts, prompt.version


def check_plans(plans: list[VariantPlan], site: ParamSite, cases: dict[str, Any]) -> None:
    seen = set(site.values)
    for plan in plans:
        if plan.base_case not in cases:
            raise PatchError(f"variant {plan.case}: base case {plan.base_case!r} has no entry")
        if plan.case in seen:
            raise PatchError(f"variant {plan.case}: the value is already a case")
        seen.add(plan.case)
        try:
            _apply(cases[plan.base_case], plan, "check", "id")
        except (EntryError, ValueError) as exc:
            raise PatchError(f"variant {plan.case}: {exc}") from exc


def _apply(
    base: dict[str, Any],
    plan: VariantPlan,
    test_id: str,
    id_field: str,
    drop: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """The base entry with the plan's changes, a new id, and no per-entry overrides (``drop``:
    priority, skip, ...), which belong to the case they were set for."""
    entry = copy.deepcopy(base)
    for key in drop:
        entry.pop(key, None)
    for change in plan.changes:
        if change.op == "delete":
            delete_path(entry, change.path)
        else:
            _set_existing(entry, change.path, json.loads(change.value_json))
    entry.pop(id_field, None)
    return {id_field: test_id, **entry}


def _set_existing(entry: dict[str, Any], path: str, value: Any) -> None:
    """Set a value whose parent exists (a plan changes the copy; it doesn't invent sections)."""
    parts = parse_path(path)
    node: Any = entry
    for part in parts[:-1]:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise EntryError(f"{path}: not found in the base entry") from exc
    last = parts[-1]
    in_object = isinstance(node, dict) and isinstance(last, str)
    in_list = isinstance(node, list) and isinstance(last, int) and last < len(node)
    if not (in_object or in_list):
        raise EntryError(f"{path}: not found in the base entry")
    node[last] = value


def _base_case(
    variant: Variant, draft: TestCaseDraft, values: list[str], cases: dict[str, Any]
) -> str:
    """The existing case whose entry shares most words with the expected outcome."""
    wanted = {
        norm(w.lower()) for w in _WORDS.findall(f"{variant.expected} {draft.expected_outcome}")
    }

    def score(case: str) -> int:
        words = {norm(w.lower()) for s in _strings(cases.get(case, {})) for w in _WORDS.findall(s)}
        return len(wanted & words)

    return max(values, key=lambda v: (score(v), -values.index(v)))


def _case_name(variant: Variant, taken: set[str]) -> str:
    if len(variant.inputs) == 1 and _CASE.fullmatch(variant.inputs[0].value):
        name = variant.inputs[0].value.lower()
    else:
        name = re.sub(r"[^a-z0-9]+", "_", variant.name.lower()).strip("_")[:40] or "case"
    found, n = name, 2
    while found in taken:
        found, n = f"{name}_{n}", n + 1
    return found


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _key_paths(entry: Any, key: str, skip: set[str], path: str = "") -> list[tuple[str, Any]]:
    """Paths to leaf values (scalars or lists of scalars) under keys named ``key``."""
    found: list[tuple[str, Any]] = []
    if isinstance(entry, dict):
        for k, v in entry.items():
            if not path and k in skip:
                continue
            here = f"{path}.{k}" if path else str(k)
            leaf = not isinstance(v, dict) and not (
                isinstance(v, list) and any(isinstance(i, dict | list) for i in v)
            )
            if leaf and _key(str(k)) == key:
                found.append((here, v))
            elif not leaf:
                found += _key_paths(v, key, skip, here)
    elif isinstance(entry, list):
        for i, v in enumerate(entry):
            found += _key_paths(v, key, skip, f"{path}.{i}")
    return found


def _case_from_argument(variant: Variant, site: ParamSite) -> str | None:
    """The new parametrize value, when one of the draft's inputs is named like the argument
    (``browser_limit`` = 2 for the argument ``limit``): the value the test receives."""
    wanted = {norm(w) for w in split_identifier(site.argname)}
    for given in variant.inputs:
        words = {norm(w) for w in split_identifier(_key(given.name))}
        if wanted and wanted <= words:
            value = given.value.strip()
            if site.numeric and not value.lstrip("-").isdigit():
                return None
            return str(int(value)) if site.numeric else value
    return None


def _dependents(
    entry: dict[str, Any], path: str, old: Any, expectations: set[str] | None = None
) -> tuple[list[str], bool]:
    """Other values in the entry that follow from ``old``: (paths of exact copies, whether any
    value is derived from it).

    Exact copies (``file`` restated in an expected response) change with it. A derived value
    (one that contains it, or that it matches as a pattern, e.g. a DLP pattern and the content
    it must find) can't be updated in code, so the case needs the LLM.
    """
    if isinstance(old, int | float) and not isinstance(old, bool):
        # a number restated in the expectations (e.g. an open count equal to the limit) is
        # the same fact; equal numbers in seed data may be coincidence and stay
        sections = expectations or set()
        restated = [
            other
            for other, value in _leaves(entry)
            if other != path
            and other.split(".", 1)[0] in sections
            and type(value) is type(old)
            and value == old
        ]
        return restated, False
    if not isinstance(old, str) or len(old) < 3:
        return [], False
    try:
        pattern: re.Pattern[str] | None = re.compile(old) if re.escape(old) != old else None
    except re.error:
        pattern = None
    copies: list[str] = []
    derived = False
    for other, value in _leaves(entry):
        if other == path or not isinstance(value, str):
            continue
        if value == old:
            copies.append(other)
        elif old in value or (pattern is not None and pattern.search(value)):
            derived = True
    return copies, derived


def _leaves(value: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        return [x for k, v in value.items() for x in _leaves(v, f"{path}.{k}" if path else k)]
    if isinstance(value, list):
        return [x for i, v in enumerate(value) for x in _leaves(v, f"{path}.{i}")]
    return [(path, value)]


def _coerce(text: str, current: Any) -> tuple[bool, Any]:
    """The draft's value (always text) in the type of the value it replaces."""
    if isinstance(current, str) or current is None:
        return True, text
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return False, None
    if isinstance(current, bool):
        return isinstance(value, bool), value
    if isinstance(current, int | float):
        return isinstance(value, int | float) and not isinstance(value, bool), value
    return isinstance(value, type(current)), value


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    return []


# --- variant patch ------------------------------------------------------------------------------


def variant_patch(
    draft: TestCaseDraft,
    decision: ReuseDecision,
    index: IndexData,
    settings: Settings,
    repo_root: Path,
    client: LLMClient | None = None,
    provider: str = "",
    model: str = "",
) -> GeneratedTest:
    chunk = next((c for c in index.chunks if c.id == decision.target), None)
    if chunk is None:
        raise PatchError(f"variant target {decision.target} is not in the index")
    if chunk.inherited_from:
        raise PatchError(
            f"{chunk.symbol_name} is inherited from {chunk.inherited_from}; a new case there "
            "changes every class that inherits it"
        )
    source = (repo_root / chunk.file_path).read_text(encoding="utf-8")
    site = parametrize_site(source, chunk.class_name, chunk.symbol_name)
    cases = cases_of(chunk)
    plans = plan_variants_in_code(draft, chunk, site, settings)
    attempts, version = 0, CODE_PLAN
    if plans is None:
        if client is None:
            raise PatchError(
                "the draft's variant inputs don't each name one data key, or other values depend "
                "on the ones they change; planning the new case needs the LLM"
            )
        plans, attempts, version = plan_variants_with_llm(draft, chunk, site, settings, client)
    if not plans:
        raise PatchError(f"every variant in the draft is already a case of {chunk.symbol_name}")
    check_plans(plans, site, cases)

    function, id_field = chunk.symbol_name, settings.data.id_field
    new_entries = [
        _apply(
            cases[p.base_case], p, f"{function}[{p.case}]", id_field, settings.data.per_entry_keys
        )
        for p in plans
    ]
    data_name = chunk.data_file or module_data_path(chunk.file_path, settings.index)
    entries, layout, data_text = read_suite_data(repo_root, chunk.file_path, settings, data_name)
    all_entries = _insert_after(entries, new_entries, function, id_field)
    after_code = site.insert(source, [p.case for p in plans])
    mine = [i for i, e in enumerate(entries) if function_of(str(e.get(id_field, ""))) == function]
    after_data = _data_after(
        data_text, all_entries, new_entries, mine[-1] if mine else None, layout, settings
    )
    patches = [
        FilePatch(chunk.file_path, source, after_code),
        FilePatch(data_name, data_text or "", after_data),
    ]
    notes = [p.notes for p in plans if p.notes]
    return GeneratedTest(
        code=after_code,
        file_name=chunk.file_path,
        data_file_name=data_name,
        data_entries=all_entries,
        data_format=layout,
        test_ids=[*static_ids(index, chunk.file_path), *(f"{function}[{p.case}]" for p in plans)],
        template_entry_ref=TemplateEntryRef(
            chunk_id=chunk.id, entry_key=f"{function}[{plans[0].base_case}]"
        ),
        ticket_id=draft.ticket_id,
        draft_ref=draft.id,
        retrieved_chunk_ids=[chunk.id],
        prompt_version=version,
        provider=provider if attempts else "",
        model=model if attempts else "",
        attempts=attempts,
        context_tokens=0,
        review_checklist=[*settings.generate.review_checklist_defaults, *notes],
        reuse_kind="variant",
        reuse_target=chunk.id,
        reuse_reasons=list(decision.reasons),
        variant_plans=plans,
        patches=[p.record() for p in patches],
        new_test_ids=[f"{function}[{p.case}]" for p in plans],
    )


def _data_after(
    data_text: str | None,
    all_entries: list[dict[str, Any]],
    new: list[dict[str, Any]],
    after: int | None,
    layout: DataFormat,
    settings: Settings,
) -> str:
    """The data file after the patch. With ``style.follow_local``, the new entries are inserted
    as text in the file's own JSON style (existing lines unchanged); otherwise, or when the file
    can't be edited that way, the whole file is written in the configured style."""
    if settings.style.follow_local and data_text and layout == "array":
        local = detect_json_style(data_text, settings.style.json_files)
        text = insert_entries(data_text, new, after, local)
        if text is not None:
            return text
    return format_entries(all_entries, settings.data, settings.style.json_files, layout)


def _insert_after(
    entries: list[dict[str, Any]], new: list[dict[str, Any]], function: str, id_field: str
) -> list[dict[str, Any]]:
    """``new`` after the last entry of ``function`` (at the end when it has none)."""
    mine = [i for i, e in enumerate(entries) if function_of(str(e.get(id_field, ""))) == function]
    at = mine[-1] + 1 if mine else len(entries)
    return [*entries[:at], *new, *entries[at:]]


# --- method patch -------------------------------------------------------------------------------


def method_retrieval(
    retrieval: RetrievalResult, index: IndexData, class_name: str, file_path: str
) -> RetrievalResult:
    """The retrieval with the target class's tests first among the templates, so the generator
    copies that class's scaffold, data shape and style."""
    in_class = {
        c.id: c
        for c in index.chunks
        if c.kind == "test" and c.class_name == class_name and c.file_path == file_path
    }
    templates = [t for t in retrieval.templates if t.chunk_id in in_class]
    if not templates:
        templates = [
            TemplateRef(chunk_id=c.id, entry_key=key, why=f"a test of {class_name}")
            for c in in_class.values()
            for key in list(c.data_entries)[:1]
        ][:1]
    if not templates:
        raise PatchError(f"no test in {class_name} has a data entry to use as a template")
    rest = [t for t in retrieval.templates if t.chunk_id not in in_class]
    return retrieval.model_copy(update={"templates": [*templates, *rest]})


def splice_methods(
    source: str, class_name: str, generated_code: str, settings: Settings
) -> tuple[str, list[str]]:
    """The file with the generated class's new methods appended to ``class_name`` and the
    imports it lacks added; returns (code, names of the methods added)."""
    target_tree = ast.parse(source)
    target = next(
        (n for n in target_tree.body if isinstance(n, ast.ClassDef) and n.name == class_name),
        None,
    )
    if target is None:
        raise PatchError(f"class {class_name} not found")
    gen_tree = ast.parse(generated_code)
    prefix = settings.index.test_class_prefix
    gen_class = next(
        (n for n in gen_tree.body if isinstance(n, ast.ClassDef) and n.name.startswith(prefix)),
        None,
    )
    if gen_class is None:
        raise PatchError("the generated code has no test class")
    existing = {n.name for n in target.body if isinstance(n, ast.FunctionDef)}
    skip = set(settings.generate.scaffold_methods) | existing
    methods = [n for n in gen_class.body if isinstance(n, ast.FunctionDef) and n.name not in skip]
    if not any(m.name.startswith(settings.index.test_function_prefix) for m in methods):
        raise PatchError("the generated class has no new test method")

    gen_lines = generated_code.splitlines(keepends=True)
    lines = source.splitlines(keepends=True)
    body_indent = _indent(lines[target.body[0].lineno - 1])
    blank = _blank_lines_between_methods(target, lines)
    blocks = []
    for method in methods:
        start = min([method.lineno, *(d.lineno for d in method.decorator_list)])
        text = "".join(gen_lines[start - 1 : method.end_lineno])
        own = _indent(gen_lines[start - 1])
        blocks.append(
            "".join(
                body_indent + line[len(own) :] if line.startswith(own) else line
                for line in text.splitlines(keepends=True)
            )
        )
    insert_at = target.end_lineno or target.lineno
    addition = "".join("\n" * blank + block for block in blocks)
    if not lines[insert_at - 1].endswith("\n"):
        addition = "\n" + addition
    patched = [*lines[:insert_at], addition, *lines[insert_at:]]

    have = _bound_by_imports(target_tree)
    used = {
        n.id for m in methods for n in ast.walk(m) if isinstance(n, ast.Name)
    }  # names the added methods use (imports for anything else stay out)
    new_imports = [
        ast.get_source_segment(generated_code, node) or ""
        for node in gen_tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        and _local_names(node) & used
        and not _bound_by_imports(ast.Module(body=[node], type_ignores=[])) <= have
        and not (isinstance(node, ast.ImportFrom) and f"{node.module}:*" in have)  # star-bound
    ]
    if new_imports:
        last_import = max(
            (
                n.end_lineno or n.lineno
                for n in target_tree.body
                if isinstance(n, ast.Import | ast.ImportFrom)
            ),
            default=0,
        )
        patched.insert(last_import, "".join(f"{i}\n" for i in new_imports))
    return "".join(patched), [m.name for m in methods]


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _blank_lines_between_methods(cls: ast.ClassDef, lines: list[str]) -> int:
    funcs = [n for n in cls.body if isinstance(n, ast.FunctionDef)]
    if len(funcs) < 2:
        return 1
    prev, last = funcs[-2], funcs[-1]
    start = min([last.lineno, *(d.lineno for d in last.decorator_list)])
    between = lines[(prev.end_lineno or prev.lineno) : start - 1]
    return max(1, sum(1 for line in between if not line.strip()))


def _local_names(node: ast.Import | ast.ImportFrom) -> set[str]:
    return {(a.asname or a.name).split(".")[0] for a in node.names}


def _bound_by_imports(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names |= {f"{node.module}:{a.asname or a.name}" for a in node.names}
    return names


def method_patch(
    generated: GeneratedTest,
    decision: ReuseDecision,
    index: IndexData,
    settings: Settings,
    repo_root: Path,
) -> GeneratedTest:
    """Turn a generated module into a patch of the existing class ``decision.target``."""
    class_name, file_path = decision.target, decision.target_file
    if not class_name or not file_path:
        raise PatchError("a method decision needs its class and file")
    source = (repo_root / file_path).read_text(encoding="utf-8")
    style = settings.style.python
    if settings.style.follow_local:  # the new methods take the file's style; nothing else moves
        local = detect_python_style(source, style)
        code = format_python(generated.code, local, first_party(index, settings))
        after_code, added = splice_methods(source, class_name, code, settings)
        if _imports(after_code) != _imports(source):  # an import was added: sort that block only
            after_code = sort_imports(after_code, local, first_party(index, settings))
    else:
        spliced, added = splice_methods(source, class_name, generated.code, settings)
        after_code = format_python(spliced, style, first_party(index, settings))
    data_name = module_data_path(file_path, settings.index)
    if _function_layout(index, class_name, file_path, settings):
        if len(added) != 1:
            raise PatchError(
                f"{class_name} keeps one data file per test: a patch adds one test at a time"
            )
        data_name = function_data_path(file_path, next(iter(added)), settings.index)
    entries, layout, data_text = read_suite_data(repo_root, file_path, settings, data_name)
    id_field = settings.data.id_field
    have = {str(e.get(id_field)) for e in entries}
    ours = [  # the added methods' entries (the class already has its inherited ones)
        e for e in generated.data_entries if function_of(str(e.get(id_field))) in added
    ]
    new_ids = [i for i in generated.test_ids if function_of(i) in added]
    clash = [e[id_field] for e in ours if str(e.get(id_field)) in have]
    if clash:
        raise PatchError(f"entries already exist for {clash}; the new test needs another name")
    all_entries = [*entries, *ours]
    after_data = _data_after(data_text, all_entries, ours, None, layout, settings)
    patches = [
        FilePatch(file_path, source, after_code),
        FilePatch(data_name, data_text or "", after_data),
    ]
    return generated.model_copy(
        update={
            "code": after_code,
            "file_name": file_path,
            "data_file_name": data_name,
            "data_entries": all_entries,
            "data_format": layout,
            "test_ids": [*static_ids(index, file_path), *new_ids],
            "new_test_ids": new_ids,
            "reuse_kind": "method",
            "reuse_target": class_name,
            "reuse_reasons": list(decision.reasons),
            "patches": [p.record() for p in patches],
        }
    )


def _imports(code: str) -> list[str]:
    return [ast.dump(n) for n in ast.parse(code).body if isinstance(n, ast.Import | ast.ImportFrom)]


def _function_layout(index: IndexData, class_name: str, file_path: str, settings: Settings) -> bool:
    """The class's tests keep their data in files named after each test function."""
    return any(
        layout_of(c.file_path, c.symbol_name, c.data_file, settings.index) == "function"
        for c in index.chunks
        if c.kind == "test" and c.file_path == file_path and c.class_name == class_name
    )


# --- validation of a patched file ---------------------------------------------------------------


def validate_patch(
    generated: GeneratedTest,
    index: IndexData,
    settings: Settings,
    repo_root: Path,
    draft: TestCaseDraft | None = None,
) -> ValidationReport:
    """Validate the whole patched file; report only findings the unpatched file doesn't have."""
    roots, imports = first_party(index, settings), module_imports(index)
    entries, layout, data_text = read_suite_data(
        repo_root, generated.file_name, settings, generated.data_file_name
    )
    before = generated.model_copy(
        update={
            "code": (repo_root / generated.file_name).read_text(encoding="utf-8"),
            "data_entries": entries,
            "data_format": layout,
            "test_ids": static_ids(index, generated.file_name),
        }
    )
    after_text = format_entries(
        generated.data_entries, settings.data, settings.style.json_files, generated.data_format
    )
    old = validate_generated(
        before, index.catalog, settings, roots, draft, data_text, imports, index
    )
    new = validate_generated(
        generated, index.catalog, settings, roots, draft, after_text, imports, index
    )
    known = Counter((f.check, f.message) for f in old.findings)
    fresh: list[Finding] = []
    for finding in new.findings:
        key = (finding.check, finding.message)
        if known[key]:
            known[key] -= 1
        else:
            fresh.append(finding)
    return ValidationReport(findings=fresh, checks_run=new.checks_run)
