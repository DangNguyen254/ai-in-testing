"""Deterministic validators for a generated test (code + data entries).

Each check returns findings; ``error`` findings block the test (and feed the repair loop),
``warning`` findings are heuristics for the reviewer. Nothing here runs the generated code.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from ticket2test.config import Settings
from ticket2test.generate.entries import function_of
from ticket2test.generate.inspect import computed_test_ids, data_use
from ticket2test.index.catalog import ClassEntry, SymbolCatalog
from ticket2test.index.tokens import split_identifier
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import GeneratedTest, _name_problems, _unconsumed_keys
from ticket2test.style import format_entries
from ticket2test.style.python import FormatError, format_python, strip_annotations
from ticket2test.validate import claims
from ticket2test.validate.code import (
    ChainResolver,
    CheckCall,
    FunctionChains,
    bound_names,
    check_calls,
    class_local_members,
    docstring,
    dotted,
    function_chains,
    markers,
    test_classes,
    test_functions,
)
from ticket2test.validate.report import Finding, Severity, ValidationReport

_PLACEHOLDER = re.compile(r"\{test_id:(\d+)\}")
_ANY_PLACEHOLDER = re.compile(r"\{[a-z_]+\d*(?::\d+)?\}")


@dataclass
class Subject:
    """Everything the checks look at, parsed once."""

    generated: GeneratedTest
    settings: Settings
    catalog: SymbolCatalog
    first_party: list[str]
    draft: TestCaseDraft | None
    data_text: str | None
    tree: ast.Module | None = None
    tests: list[tuple[ast.ClassDef | None, ast.FunctionDef]] = field(default_factory=list)
    chains: dict[str, FunctionChains] = field(default_factory=dict)  # by function name
    checks: dict[str, list[CheckCall]] = field(default_factory=dict)
    base: ClassEntry | None = None

    @property
    def code(self) -> str:
        return self.generated.code

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self.generated.data_entries

    def entries_for(self, function: str) -> list[dict[str, Any]]:
        id_field = self.settings.data.id_field
        return [e for e in self.entries if function_of(str(e.get(id_field, ""))) == function]


Check = Callable[[Subject], Iterator[Finding]]


def _f(check: str, message: str, severity: Severity = "error", **where: Any) -> Finding:
    return Finding(check=check, severity=severity, message=message, **where)


# --- code -----------------------------------------------------------------------------------


def check_syntax(s: Subject) -> Iterator[Finding]:
    try:
        s.tree = ast.parse(s.code)
    except SyntaxError as exc:
        yield _f("syntax", f"the code does not parse: {exc.msg}", line=exc.lineno)


def check_imports(s: Subject) -> Iterator[Finding]:
    assert s.tree is not None
    modules = {sym.qualname for sym in s.catalog.symbols if sym.kind == "module"}
    external = set(s.settings.validation.external_modules) | set(sys.stdlib_module_names)
    for node in ast.walk(s.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _known_module(alias.name, modules, external):
                    yield _f("imports", f"unknown module {alias.name!r}", line=node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield _f("imports", "relative imports are not used in the suite", line=node.lineno)
                continue
            module = node.module or ""
            if module in modules:
                for alias in node.names:
                    name = f"{module}.{alias.name}"
                    if not (s.catalog.find(name) or name in modules):
                        yield _f(
                            "imports", f"{module} has no name {alias.name!r}", line=node.lineno
                        )
            elif not _known_module(module, modules, external):
                yield _f("imports", f"unknown module {module!r}", line=node.lineno)


def _known_module(name: str, modules: set[str], external: set[str]) -> bool:
    return name in modules or name.split(".")[0] in external


def check_names(s: Subject) -> Iterator[Finding]:
    """Plain names must be bound somewhere in the module (imports, definitions, locals)."""
    assert s.tree is not None
    bound = bound_names(s.tree)
    for node in ast.walk(s.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
            yield _f("names", f"undefined name {node.id!r}", line=node.lineno)


def check_base_class(s: Subject) -> Iterator[Finding]:
    assert s.tree is not None
    base_name = s.settings.validation.base_class
    if s.base is None:
        yield _f("base_class", f"base class {base_name!r} is not in the target repo's catalog")
        return
    for cls in test_classes(s.tree, s.settings.index.test_class_prefix):
        names = [dotted(b) for b in cls.bases]
        inherits = any(
            n.rsplit(".", 1)[-1] == base_name
            or any(e.name == base_name for e in _mro_by_name(s.catalog, n))
            for n in names
        )
        if not inherits:
            yield _f("base_class", f"class {cls.name} must inherit {base_name}", line=cls.lineno)


def _mro_by_name(catalog: SymbolCatalog, name: str) -> list[ClassEntry]:
    entry = catalog.class_named(name)
    return catalog.mro(entry.qualname) if entry else []


def check_chains(s: Subject) -> Iterator[Finding]:
    """Page-object chains exist; properties are read or assigned, actions are called."""
    page_objects = set(s.catalog.page_objects)
    for function, found in s.chains.items():
        for use in found.uses:
            if use.status == "missing":
                yield _f("names", f"{use.message} (in {use.text})", test=function, line=use.line)
                continue
            for index, step in enumerate(use.steps):
                last = index == len(use.steps) - 1
                if step.kind == "property" and step.called:
                    yield _f(
                        "page_objects",
                        f"{step.name} is a property: read or assign it, don't call it",
                        test=function,
                        line=use.line,
                    )
                elif step.kind == "method" and not step.called and not (last and use.store):
                    yield _f(
                        "page_objects",
                        f"{step.name} is an action method: call it ({use.text})",
                        test=function,
                        line=use.line,
                    )
                elif step.kind == "method" and last and use.store:
                    yield _f(
                        "page_objects",
                        f"{step.name} is an action method; it can't be assigned",
                        test=function,
                        line=use.line,
                    )
                if step.called and not last and step.owner in page_objects:
                    yield _f(
                        "page_objects",
                        f"no chaining: keep the page in a variable and call {step.name}() "
                        f"on its own line ({use.text})",
                        test=function,
                        line=use.line,
                    )


def check_assertions(s: Subject) -> Iterator[Finding]:
    v = s.settings.validation
    allowed = set(v.assertion_methods)
    for _, fn in s.tests:
        if any(isinstance(n, ast.Assert) for n in ast.walk(fn)):
            yield _f(
                "assertions",
                f"use the suite's assertion object ({v.assertion_object}), not a bare assert",
                test=fn.name,
                line=fn.lineno,
            )
        calls = s.checks.get(fn.name, [])
        for call in calls:
            if not call.helper and call.method not in allowed:
                yield _f(
                    "assertions",
                    f"{v.assertion_object}.{call.method} is not an allowed assertion "
                    f"(allowed: {', '.join(sorted(allowed))})",
                    test=fn.name,
                    line=call.line,
                )
        if not calls:
            yield _f(
                "assertions",
                "the test checks nothing: add an assertion or call the validation helper",
                test=fn.name,
                line=fn.lineno,
            )


def check_markers(s: Subject) -> Iterator[Finding]:
    m = s.settings.markers
    allowed: dict[str, set[str]] = {
        "priority": set(m.priorities),
        "suite": set(m.suites),
        "project": {m.project, *s.catalog.markers.get("project", [])},
        "component": set(s.catalog.markers.get("component", [])),
    }
    for cls, fn in s.tests:
        found = markers(cls.decorator_list if cls else [])
        for name, values in markers(fn.decorator_list).items():
            found.setdefault(name, []).extend(values)
        for name in m.required:
            values = found.get(name, [])
            if not values:
                yield _f("markers", f"missing @pytest.mark.{name}(...)", test=fn.name)
                continue
            known = allowed.get(name)
            for value in values:
                if known and value not in known:
                    yield _f(
                        "markers",
                        f"{name} value {value!r} is not approved (known: "
                        f"{', '.join(sorted(known))})",
                        test=fn.name,
                    )


def check_naming(s: Subject) -> Iterator[Finding]:
    assert s.tree is not None
    n = s.settings.validation.naming
    module = PurePosixPath(s.generated.file_name).stem
    if not re.fullmatch(n.module, module):
        yield _f("naming", f"module name {module!r} doesn't match {n.module}")
    for cls in test_classes(s.tree, s.settings.index.test_class_prefix):
        if not re.fullmatch(n.test_class, cls.name):
            yield _f("naming", f"class name {cls.name!r} doesn't match {n.test_class}")
    for _, fn in s.tests:
        if not re.fullmatch(n.test_function, fn.name):
            yield _f("naming", f"test name {fn.name!r} doesn't match {n.test_function}")
    names = [module, *(c.name for c in test_classes(s.tree, "")), *(f.name for _, f in s.tests)]
    for problem in _name_problems(names, s.generated.ticket_id):
        yield _f("naming", problem)


def check_style(s: Subject) -> Iterator[Finding]:
    style = s.settings.style.python
    code = s.code
    if style.line_ending == "lf" and "\r" in code:
        yield _f("style", "line endings must be LF")
    if style.final_newline and not code.endswith("\n"):
        yield _f("style", "the file must end with a newline")
    if style.strip_annotations and strip_annotations(code) != code:
        yield _f("style", "type annotations are not used in the suite")
    try:
        formatted = format_python(code, style, s.first_party)
    except FormatError as exc:
        yield _f("style", f"could not check formatting: {exc}", "warning")
        return
    if formatted != code:
        yield _f("style", "the code is not formatted to the suite's style (indent, imports)")


# --- data -----------------------------------------------------------------------------------


def check_ids_and_entries(s: Subject) -> Iterator[Finding]:
    d = s.settings.data
    try:
        ids = computed_test_ids(
            s.code, s.settings.index.test_function_prefix, s.settings.index.test_class_prefix
        )
    except ValueError as exc:
        yield _f("ids", str(exc))
        return
    keys = [e.get(d.id_field) for e in s.entries]
    if any(not isinstance(k, str) for k in keys):
        yield _f("ids", f"every entry needs a string {d.id_field!r}")
    duplicates = sorted({k for k in keys if isinstance(k, str) and keys.count(k) > 1})
    if duplicates:
        yield _f("ids", f"duplicate entries: {duplicates}")
    orphans = [k for k in keys if isinstance(k, str) and k not in ids]
    if orphans:
        yield _f("ids", f"entries for ids the code doesn't produce: {orphans} (computed: {ids})")
    uses = _uses(s)
    for test_id in ids:
        use = uses.get(function_of(test_id))
        if use and use.reads_data and test_id not in keys:
            yield _f("ids", "the test reads its data entry but has none", test=test_id)
    if sorted(ids) != sorted(s.generated.test_ids):
        yield _f("ids", f"recorded test ids {s.generated.test_ids} differ from the code's {ids}")


def check_data_keys(s: Subject) -> Iterator[Finding]:
    """Keys the test reads exist in each entry; every key is read or consumed (rule 1)."""
    d = s.settings.data
    uses = _uses(s)
    ctx = {
        "id_field": d.id_field,
        "seed_sections": d.seed_sections,
        "per_entry_keys": d.per_entry_keys,
        "expectation_sections": d.expectation_sections,
    }
    for entry in s.entries:
        test_id = str(entry.get(d.id_field, ""))
        use = uses.get(function_of(test_id))
        absent = sorted(use.keys - set(entry)) if use else []
        if absent:
            yield _f("data_keys", f"reads keys its entry lacks: {absent}", test=test_id)
        unused = _unconsumed_keys(entry, use, ctx)
        if unused:
            yield _f("data_keys", unused, test=test_id)


def check_data_file(s: Subject) -> Iterator[Finding]:
    d = s.settings.data
    if not all(isinstance(e, dict) for e in s.entries):
        yield _f("data_file", "every entry must be a JSON object")
        return
    if s.data_text is None:
        return
    expected = format_entries(s.entries, d, s.settings.style.json_files, s.generated.data_format)
    if s.data_text != expected:
        yield _f("data_file", "the data file is not formatted to the suite's JSON style")


def check_seeded_names(s: Subject) -> Iterator[Finding]:
    """Seeded object names use the unique-name placeholder and fit the name length limit."""
    v = s.settings.validation
    cap = v.name_max_length
    for entry in s.entries:
        test_id = str(entry.get(s.settings.data.id_field, ""))
        for section in s.settings.data.seed_sections:
            for key, value in _keyed_strings(entry.get(section)):
                if key in v.name_keys and not _ANY_PLACEHOLDER.search(value):
                    yield _f(
                        "names_unique",
                        f"seeded name {value!r} is a literal: use the unique-name placeholder "
                        f"(e.g. {s.settings.generate.placeholder_token})",
                        test=test_id,
                    )
        for value in _strings(entry):
            for match in _PLACEHOLDER.finditer(value):
                length = int(match.group(1)) + len(_PLACEHOLDER.sub("", value))
                if length > cap:
                    yield _f(
                        "name_length",
                        f"{value!r} can be {length} characters; the limit is {cap}",
                        test=test_id,
                    )
    helper = v.unique_name_helper
    assert s.tree is not None
    for node in ast.walk(s.tree):
        if isinstance(node, ast.Call) and dotted(node.func) == helper and node.args:
            limit = node.args[0]
            if (
                isinstance(limit, ast.Constant)
                and isinstance(limit.value, int)
                and limit.value > cap
            ):
                yield _f(
                    "name_length",
                    f"{helper}({limit.value}) exceeds the name limit {cap}",
                    line=node.lineno,
                )
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr in v.name_keys
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    yield _f(
                        "names_unique",
                        f"typed name {node.value.value!r} is a literal: use {helper}(N) or the "
                        "entry's placeholder name",
                        line=node.lineno,
                    )


def check_capability_gates(s: Subject) -> Iterator[Finding]:
    """Seed only the gates the component's features use (warning)."""
    v = s.settings.validation
    path = v.capability_path.split(".")
    for cls, fn in s.tests:
        found = markers(cls.decorator_list if cls else [])
        found.update(markers(fn.decorator_list))
        component = (found.get("component") or [""])[0]
        allowed = v.capability_gates.get(component)
        if allowed is None:
            continue
        for entry in s.entries_for(fn.name):
            blocks = [entry, *(t for t in entry.get("tenants", []) if isinstance(t, dict))]
            gates: set[str] = set()
            for block in blocks:
                found_gates = _get_path(block, path)
                if isinstance(found_gates, dict):
                    gates |= set(found_gates)
            extra = sorted(gates - set(allowed))
            if extra:
                yield _f(
                    "capabilities",
                    f"seeds capability gates {component!r} features don't use: {extra}",
                    "warning",
                    test=str(entry.get(s.settings.data.id_field)),
                )


# --- heuristics (warnings) ------------------------------------------------------------------


def check_claims(s: Subject) -> Iterator[Finding]:
    sections = s.settings.data.expectation_sections
    generic = {s.settings.index.test_function_prefix}
    ignore = frozenset(
        p.rsplit(".", 1)[-1]
        for p in [*s.settings.data.access, s.settings.validation.assertion_object]
    )
    assert s.tree is not None
    for cls, fn in s.tests:
        found = markers(cls.decorator_list if cls else [])
        generic.update(v for v in found.get("component", []))
        sources: list[tuple[str, str]] = [
            ("docstring", c) for c in claims.outcome_claims(docstring(fn))
        ]
        if not sources:  # no docstring outcome: the name is the only claim
            name = claims.name_claim(fn.name, s.settings.index.test_function_prefix, generic)
            if name:
                sources.append(("name", name))
        chains = s.chains.get(fn.name)
        actions = {
            claims.norm(w)
            for use in (chains.uses if chains else [])
            for step in use.steps
            for w in split_identifier(step.name)
        }
        gaps = claims.find_gaps(
            sources,
            s.checks.get(fn.name, []),
            s.entries_for(fn.name),
            sections,
            ignore,
            actions=actions,
        )
        for gap in gaps:
            yield _f(
                "claims",
                f"{gap.source} claims {gap.clause!r}: {gap.reason}",
                "warning",
                test=fn.name,
            )


def check_draft_outcome(s: Subject) -> Iterator[Finding]:
    """The draft's expected outcome is about the module: some test must check it."""
    if s.draft is None or not s.draft.expected_outcome:
        return
    ignore = frozenset(
        p.rsplit(".", 1)[-1]
        for p in [*s.settings.data.access, s.settings.validation.assertion_object]
    )
    all_checks = [c for _, fn in s.tests for c in s.checks.get(fn.name, [])]
    gaps = claims.find_gaps(
        [("expected outcome", s.draft.expected_outcome)],
        all_checks,
        s.entries,
        s.settings.data.expectation_sections,
        ignore,
    )
    for gap in gaps:
        yield _f("claims", f"{gap.source} claims {gap.clause!r}: {gap.reason}", "warning")


def check_unstated_constants(s: Subject) -> Iterator[Finding]:
    v = s.settings.validation
    paging = set(v.paging_actions)
    constants = set(v.constant_properties)
    for _, fn in s.tests:
        uses = s.chains.get(fn.name)
        if uses is None:
            continue
        names = {step.name for use in uses.uses for step in use.steps}
        if not names & paging or names & constants:
            continue
        counts = any(
            isinstance(n, ast.Call) and dotted(n.func) == "len"
            for c in s.checks.get(fn.name, [])
            for n in ast.walk(c.node)
        )
        if counts:
            yield _f(
                "constants",
                f"pages through results and checks a count, but never reads "
                f"{' / '.join(sorted(constants))}: the expected numbers depend on an unstated "
                "page size",
                "warning",
                test=fn.name,
            )


# --- orchestration --------------------------------------------------------------------------

CHECKS: list[tuple[str, Check]] = [
    ("imports", check_imports),
    ("names", check_names),
    ("base_class", check_base_class),
    ("chains", check_chains),
    ("assertions", check_assertions),
    ("markers", check_markers),
    ("naming", check_naming),
    ("style", check_style),
    ("ids", check_ids_and_entries),
    ("data_keys", check_data_keys),
    ("data_file", check_data_file),
    ("seeded_names", check_seeded_names),
    ("capabilities", check_capability_gates),
    ("claims", check_claims),
    ("draft_outcome", check_draft_outcome),
    ("constants", check_unstated_constants),
]


def validate_generated(
    generated: GeneratedTest,
    catalog: SymbolCatalog,
    settings: Settings,
    first_party: list[str] | None = None,
    draft: TestCaseDraft | None = None,
    data_text: str | None = None,
) -> ValidationReport:
    """Run every check. ``data_text`` is the written data file, if any (checks formatting)."""
    subject = Subject(generated, settings, catalog, first_party or [], draft, data_text)
    report = ValidationReport(checks_run=["syntax"])
    report.findings += list(check_syntax(subject))
    if subject.tree is None:
        return report
    _prepare(subject)
    for name, check in CHECKS:
        report.checks_run.append(name)
        report.findings += list(check(subject))
    return report


def _prepare(s: Subject) -> None:
    assert s.tree is not None
    v, d = s.settings.validation, s.settings.data
    s.base = s.catalog.class_named(v.base_class)
    s.tests = test_functions(
        s.tree, s.settings.index.test_function_prefix, s.settings.index.test_class_prefix
    )
    helpers = set(d.expectation_sections.values())
    for cls, fn in s.tests:
        local = class_local_members(cls) if cls else set()
        resolver = ChainResolver(s.catalog, s.base, local)
        s.chains[fn.name] = function_chains(fn, resolver)
        s.checks[fn.name] = check_calls(fn, v.assertion_object, helpers)


def _uses(s: Subject) -> dict[str, Any]:
    d = s.settings.data
    return data_use(
        s.code,
        d.access,
        list(d.expectation_sections.values()),
        s.settings.index.test_function_prefix,
    )


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _keyed_strings(value: Any) -> Iterator[tuple[str, str]]:
    if isinstance(value, list):
        for item in value:
            yield from _keyed_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                yield key, item
            else:
                yield from _keyed_strings(item)


def _get_path(value: Any, path: list[str]) -> Any:
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value
