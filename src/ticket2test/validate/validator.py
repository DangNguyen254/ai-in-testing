"""Deterministic validators for a generated test (code + data entries).

Each check returns findings; ``error`` findings block the test (and feed the repair loop),
``warning`` findings are heuristics for the reviewer. Nothing here runs the generated code.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from ticket2test.config import Settings
from ticket2test.generate.entries import function_of
from ticket2test.generate.inspect import DataUse, computed_test_ids, data_use
from ticket2test.index.catalog import ClassEntry, SymbolCatalog
from ticket2test.index.chunks import is_test_file
from ticket2test.index.datafile import merged, split_defaults
from ticket2test.index.indexer import IndexData
from ticket2test.index.tokens import split_identifier
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import GeneratedTest, _name_problems, _unconsumed_keys
from ticket2test.security.masking import TOKEN
from ticket2test.security.private import MARK, PrivateTerms
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
from ticket2test.validate.datause import Resolver
from ticket2test.validate.report import Finding, Severity, ValidationReport


@dataclass
class Subject:
    """Everything the checks look at, parsed once."""

    generated: GeneratedTest
    settings: Settings
    catalog: SymbolCatalog
    first_party: list[str]
    draft: TestCaseDraft | None
    data_text: str | None
    module_imports: dict[str, list[str]] = field(default_factory=dict)  # module -> imports
    tree: ast.Module | None = None
    tests: list[tuple[ast.ClassDef | None, ast.FunctionDef]] = field(default_factory=list)
    chains: dict[str, FunctionChains] = field(default_factory=dict)  # by function name
    checks: dict[str, list[CheckCall]] = field(default_factory=dict)
    base: ClassEntry | None = None
    index: IndexData | None = None
    resolver: Resolver | None = None
    uses: dict[str, DataUse] = field(default_factory=dict)  # by test function name
    inherited_ids: list[str] = field(default_factory=list)  # ids of inherited tests
    deep_checks: dict[str, bool] = field(default_factory=dict)  # checks via called methods

    @property
    def code(self) -> str:
        return self.generated.code

    @property
    def entries(self) -> list[dict[str, Any]]:
        """The test entries, without a defaults row."""
        return split_defaults(self.generated.data_entries, self.settings.data)[1]

    @property
    def defaults(self) -> dict[str, Any] | None:
        """The data file's defaults row: in the written entries (a patched file), or in the
        indexed file the generated test writes to."""
        own, _ = split_defaults(self.generated.data_entries, self.settings.data)
        if own is not None or self.index is None:
            return own
        name = self.generated.data_file_name
        found = next(
            (c for c in self.index.chunks if c.data_file == name and c.data_defaults), None
        )
        return found.data_defaults if found else None

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
                    reexported = _reexports(s.module_imports.get(module, []), alias.name)
                    if not (s.catalog.find(name) or name in modules or reexported):
                        yield _f(
                            "imports", f"{module} has no name {alias.name!r}", line=node.lineno
                        )
            elif not _known_module(module, modules, external):
                yield _f("imports", f"unknown module {module!r}", line=node.lineno)


def _reexports(imports: list[str], name: str) -> bool:
    """The module imports ``name`` itself (e.g. a package ``__init__`` re-exporting it)."""
    word = re.compile(rf"\b{re.escape(name)}\b")
    return any(
        " import " in f" {line} " and word.search(line.split("import", 1)[1]) for line in imports
    )


def module_imports(index: IndexData) -> dict[str, list[str]]:
    """Top-level import statements per module of the indexed repo."""
    return {
        record.info.module: record.info.imports
        for record in index.files.values()
        if record.info is not None
    }


def _known_module(name: str, modules: set[str], external: set[str]) -> bool:
    return name in modules or name.split(".")[0] in external


def check_names(s: Subject) -> Iterator[Finding]:
    """Plain names must be bound somewhere in the module (imports, definitions, locals)."""
    assert s.tree is not None
    bound = bound_names(s.tree)
    for node in ast.walk(s.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
            yield _f("names", f"undefined name {node.id!r}", line=node.lineno)


def suite_base_classes(catalog: SymbolCatalog, settings: Settings) -> list[str]:
    """The configured base classes, or the in-repo classes the suite's test classes directly
    inherit (discovered; a class inheriting one of those inherits its whole lineage, while a
    mixin further up doesn't count on its own)."""
    v = settings.validation
    if v.base_classes or not v.discover_base_classes:
        return list(v.base_classes)
    prefix = settings.index.test_class_prefix
    found: dict[str, int] = {}
    for entry in catalog.classes.values():
        if entry.name.startswith(prefix) and is_test_file(entry.file_path, settings.index):
            for written in entry.bases:
                base = catalog.resolve_type(written, entry.module)
                if base is not None and not base.name.startswith(prefix):
                    found[base.name] = found.get(base.name, 0) + 1
    return sorted(found, key=lambda name: (-found[name], name))  # most used first


def check_base_class(s: Subject) -> Iterator[Finding]:
    assert s.tree is not None
    allowed = suite_base_classes(s.catalog, s.settings)
    if not allowed:
        return
    known = [b for b in allowed if s.catalog.class_named(b) is not None]
    if not known:
        yield _f(
            "base_class", f"none of the base classes {allowed} is in the target repo's catalog"
        )
        return
    for cls in test_classes(s.tree, s.settings.index.test_class_prefix):
        names = [dotted(b) for b in cls.bases]
        inherits = any(
            n.rsplit(".", 1)[-1] in allowed
            or any(e.name in allowed for e in _mro_by_name(s.catalog, n))
            for n in names
        )
        if not inherits:
            shown = allowed if len(allowed) <= 6 else [*allowed[:6], "..."]
            wanted = allowed[0] if len(allowed) == 1 else f"one of {', '.join(shown)}"
            yield _f("base_class", f"class {cls.name} must inherit {wanted}", line=cls.lineno)


_SPLIT_ON_DOT = re.compile(r"""\.split\(\s*["']\.["']\s*\)""")


def path_string_helpers(index: IndexData | None, settings: Settings) -> set[str]:
    """Helper names that resolve a dotted page-object path string with getattr."""
    v = settings.validation
    found = set(v.path_string_helpers)
    if v.discover_path_string_helpers and index is not None:
        for chunk in index.chunks:
            if (
                chunk.kind == "function"
                and "getattr(" in chunk.code
                and _SPLIT_ON_DOT.search(chunk.code)
            ):
                found.add(chunk.symbol_name)
    return found


def check_path_strings(s: Subject) -> Iterator[Finding]:
    """A dotted page-object path passed as a string (``navigate("rules.list")``) must resolve
    through the catalog, from a chain root, like a property chain does."""
    helpers = path_string_helpers(s.index, s.settings)
    roots = list(s.catalog.chain_roots)
    if not helpers or not roots:
        return
    for _, fn in s.tests:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if dotted(node.func).rsplit(".", 1)[-1] not in helpers:
                continue
            arg = node.args[0]
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                continue  # built at run time: can't be checked statically
            text = arg.value.strip().strip(".")
            if not text:
                continue
            tries = [text] if text.split(".")[0] in roots else [f"{r}.{text}" for r in roots]
            results = [s.catalog.resolve_chain_from_roots(t) for t in tries]
            # Like chains: only a member that is missing is an error; a type that can't be
            # followed statically ("unknown_type") is not.
            if all(r.status in ("missing", "no_root") for r in results):
                yield _f(
                    "names",
                    f"page path {arg.value!r} doesn't resolve: {results[0].message}",
                    test=fn.name,
                    line=node.lineno,
                )


_HOOK_ROLES = {
    "setup": ("setup", "setup_method", "setUp", "setup_class", "setUpClass"),
    "teardown": ("teardown", "teardown_method", "tearDown", "teardown_class", "tearDownClass"),
}


def check_hooks(s: Subject) -> Iterator[Finding]:
    """A setup/teardown hook whose name the class's bases don't use, while they use another
    name for the same role: overriding the wrong name does nothing, or skips the base's
    setup (real suites mix setup, setup_method and setUp)."""
    if s.resolver is None or s.tree is None:
        return
    for cls in test_classes(s.tree, s.settings.index.test_class_prefix):
        own = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        bases = s.resolver.repo_bases(cls)
        for role, names in _HOOK_ROLES.items():
            used = sorted({n for b in bases for n in b.members if n in names})
            for name in sorted(own & set(names)):
                if used and name not in used:
                    yield _f(
                        "hooks",
                        f"{cls.name}.{name}: the base classes use {', '.join(used)} for "
                        f"{role}, not {name}; define {used[0]} instead so the base's {role} runs",
                        "warning",
                        line=next(n.lineno for n in cls.body
                                  if isinstance(n, ast.FunctionDef) and n.name == name),
                    )  # fmt: skip


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
        if not calls and not s.deep_checks.get(fn.name):
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
        own = computed_test_ids(
            s.code, s.settings.index.test_function_prefix, s.settings.index.test_class_prefix
        )
    except ValueError as exc:
        if not (s.inherited_ids and str(exc).startswith("no test found")):
            yield _f("ids", str(exc))
            return
        own = []  # a class that only inherits its tests
    ids = list(dict.fromkeys([*own, *s.inherited_ids]))
    keys = [e.get(d.id_field) for e in s.entries]
    if any(not isinstance(k, str) for k in keys):
        yield _f("ids", f"every entry needs a string {d.id_field!r}")
    duplicates = sorted({k for k in keys if isinstance(k, str) and keys.count(k) > 1})
    if duplicates:
        yield _f("ids", f"duplicate entries: {duplicates}")
    orphans = [k for k in keys if isinstance(k, str) and k not in ids]
    if orphans:
        yield _f("ids", f"entries for ids the code doesn't produce: {orphans} (computed: {ids})")
    uses = s.uses
    for test_id in ids:
        use = uses.get(function_of(test_id))
        if use and use.reads_data and test_id not in keys:
            yield _f("ids", "the test reads its data entry but has none", test=test_id)
    if sorted(ids) != sorted(s.generated.test_ids):
        yield _f("ids", f"recorded test ids {s.generated.test_ids} differ from the code's {ids}")


def check_data_keys(s: Subject) -> Iterator[Finding]:
    """Keys the test reads exist in each entry; every key is read or consumed (rule 1)."""
    d = s.settings.data
    uses = s.uses
    ctx = {
        "id_field": d.id_field,
        "seed_sections": d.seed_sections,
        "per_entry_keys": d.per_entry_keys,
        "expectation_sections": d.expectation_sections,
    }
    defaults = s.defaults
    for entry in s.entries:
        test_id = str(entry.get(d.id_field, ""))
        use = uses.get(function_of(test_id))
        seen = merged(entry, defaults, d)  # keys may come from the file's defaults row
        absent = sorted(use.keys - set(seen)) if use else []
        if absent:
            yield _f("data_keys", f"reads keys its entry lacks: {absent}", test=test_id)
        unused = _unconsumed_keys(entry, use, ctx)
        if unused:
            yield _f("data_keys", unused, test=test_id)


def check_data_shape(s: Subject) -> Iterator[Finding]:
    """Each value has the shape the suite uses for the same key path in its data files (a list
    where the suite always has a list, an object where it has an object, ...).

    Static checks pass an entry like ``"site": {"pages": {"/a": {...}}}`` when the suite always
    writes ``"pages": [{"path": "/a", ...}]``; the test loads, then fails when the seed is
    applied. Only paths the suite uses, with one consistent shape, are judged. Expectation
    sections are skipped: a response's shape depends on its endpoint."""
    if s.index is None:
        return
    skip = set(s.settings.data.expectation_sections)
    known: dict[str, set[str]] = {}
    own = {str(e.get(s.settings.data.id_field, "")) for e in s.entries}
    for chunk in s.index.chunks:
        for test_id, entry in chunk.data_entries.items():
            if test_id in own and chunk.file_path == s.generated.file_name:
                continue  # the entries being judged
            for path, shape in _shapes(entry, skip=skip):
                known.setdefault(path, set()).add(shape)
    reported: set[tuple[str, str]] = set()
    for entry in s.entries:
        test_id = str(entry.get(s.settings.data.id_field, ""))
        for path, shape in _shapes(entry, skip=skip):
            expected = known.get(path)
            if not expected or len(expected) != 1 or shape in expected:
                continue
            (want,) = expected
            if (path, shape) in reported:
                continue
            reported.add((path, shape))
            yield _f(
                "data_shape",
                f"{path} is {_A[shape]} here, but {_A[want]} in every data file of the suite: "
                "write it the way the existing entries do",
                test=test_id,
            )


_A = {"object": "an object", "list": "a list", "text": "text", "number": "a number",
      "bool": "true/false", "null": "null"}  # fmt: skip


def _shapes(
    value: Any, path: str = "", skip: set[str] | frozenset[str] = frozenset()
) -> Iterator[tuple[str, str]]:
    """(key path, shape) for every value; list items share the path ``a.b[]``. Keys in
    ``skip`` (the expectation sections) are left out wherever they appear."""
    if isinstance(value, dict):
        if path:
            yield path, "object"
        for key, item in value.items():
            if (not path and key == "test_id") or key in skip:
                continue
            yield from _shapes(item, f"{path}.{key}" if path else str(key), skip)
    elif isinstance(value, list):
        yield path, "list"
        for item in value:
            yield from _shapes(item, f"{path}[]", skip)
    elif isinstance(value, bool):
        yield path, "bool"
    elif isinstance(value, int | float):
        yield path, "number"
    elif isinstance(value, str):
        yield path, "text"
    else:
        yield path, "null"


def check_data_file(s: Subject) -> Iterator[Finding]:
    d = s.settings.data
    if not all(isinstance(e, dict) for e in s.entries):
        yield _f("data_file", "every entry must be a JSON object")
        return
    if s.data_text is None:
        return
    written = s.generated.data_entries  # the whole file, defaults row included
    expected = format_entries(written, d, s.settings.style.json_files, s.generated.data_format)
    if s.data_text != expected:
        yield _f("data_file", "the data file is not formatted to the suite's JSON style")


def check_seeded_names(s: Subject) -> Iterator[Finding]:
    """Seeded object names use the unique-name placeholder and fit the name length limit."""
    v = s.settings.validation
    cap = v.name_max_length
    any_placeholder = re.compile(v.placeholder_pattern)
    unique = re.compile(v.unique_name_pattern)
    for entry in s.entries:
        test_id = str(entry.get(s.settings.data.id_field, ""))
        for section in v.unique_name_sections:
            for key, value in _keyed_strings(entry.get(section)):
                if key in v.name_keys and not any_placeholder.search(value):
                    yield _f(
                        "names_unique",
                        f"seeded name {value!r} is a literal: use the unique-name placeholder "
                        f"(e.g. {s.settings.generate.placeholder_token})",
                        test=test_id,
                    )
        for value in _strings(entry):
            match = unique.match(value)  # a name starts with the placeholder; messages don't
            if match is not None:
                length = int(match.group(1)) + len(unique.sub("", value))
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


def check_variants(s: Subject) -> Iterator[Finding]:
    """Every variant the draft lists becomes a case: one of its input values appears in the
    code (a string literal, e.g. a parametrize value) or in the data. A draft asking for
    viewers and editors must not come back with viewers only."""
    if s.draft is None or not s.draft.variants:
        return
    assert s.tree is not None
    literals = {
        n.value.lower()
        for n in ast.walk(s.tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    texts = (
        literals
        | {v.lower() for v in _strings(s.entries)}
        | {i.lower() for i in s.generated.test_ids}
    )
    blob = "\n".join(texts)
    for variant in s.draft.variants:
        values = [i.value.strip().lower() for i in variant.inputs if len(i.value.strip()) > 1]
        if not values:
            continue
        if not any(v in blob or (v.endswith("s") and v[:-1] in blob) for v in values):
            shown = ", ".join(f"{i.name}={i.value!r}" for i in variant.inputs)
            yield _f(
                "variants",
                f"the draft's variant {variant.name!r} ({shown}) has no case: none of its "
                "values is in the code or the data. Add a parametrize value and an entry for it.",
            )


def check_private(s: Subject) -> Iterator[Finding]:
    """No private term (``security.private_terms``) and no redaction mark in the output. The
    term is named by its position in the list, never by its text."""
    terms = PrivateTerms(s.settings.security.private_terms)
    data_text = json.dumps(s.entries, ensure_ascii=False, indent=1)
    for where, text in (("code", s.code), ("data", data_text)):
        for hit in terms.find(text):
            yield _f(
                "private",
                f"private term #{hit.term} is in the {where} (line {hit.line})",
                line=hit.line if where == "code" else None,
            )
        if MARK in text:
            yield _f(
                "private",
                f"a redacted name {MARK} is in the {where}: the LLM only saw it redacted; "
                "the reviewer must write the real value",
            )


def check_payloads(s: Subject) -> Iterator[Finding]:
    """Masked payloads were restored, and no new instruction-like text appeared."""
    data_text = json.dumps(s.entries, ensure_ascii=False)
    for where, text in (("code", s.code), ("data", data_text)):
        for token in sorted(set(TOKEN.findall(text))):
            yield _f(
                "payloads",
                f"masked payload token [[PAYLOAD_{token}]] left in the {where}: it was not "
                "restored (an unknown token, or not inside a plain string literal)",
            )
    patterns = [re.compile(p, re.IGNORECASE) for p in s.settings.security.masking.patterns]
    if not patterns:
        return
    known = _known_texts(s)
    for value in _strings(s.entries) | _code_strings(s.tree):
        if any(p.search(value) for p in patterns) and not any(value in k for k in known):
            yield _f(
                "payloads",
                f"instruction-like text not found in the suite's data or the draft: "
                f"{value[:80]!r}. Confirm it is intended test data.",
                "warning",
            )


def _known_texts(s: Subject) -> list[str]:
    """Texts a payload may legitimately come from: the suite's data entries and the draft."""
    known: list[str] = []
    if s.index is not None:
        for chunk in s.index.chunks:
            if chunk.data_entries:
                known.append(json.dumps(chunk.data_entries, ensure_ascii=False))
                known.extend(_strings(chunk.data_entries))
    if s.draft is not None:
        known.append(s.draft.model_dump_json())
        known.extend(_strings(s.draft.model_dump()))
    return known


def _code_strings(tree: ast.Module | None) -> set[str]:
    if tree is None:
        return set()
    return {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


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
    ("data_shape", check_data_shape),
    ("seeded_names", check_seeded_names),
    ("capabilities", check_capability_gates),
    ("claims", check_claims),
    ("hooks", check_hooks),
    ("path_strings", check_path_strings),
    ("draft_outcome", check_draft_outcome),
    ("variants", check_variants),
    ("constants", check_unstated_constants),
    ("payloads", check_payloads),
    ("private", check_private),
]


def validate_generated(
    generated: GeneratedTest,
    catalog: SymbolCatalog,
    settings: Settings,
    first_party: list[str] | None = None,
    draft: TestCaseDraft | None = None,
    data_text: str | None = None,
    imports: dict[str, list[str]] | None = None,
    index: IndexData | None = None,
) -> ValidationReport:
    """Run every check. ``data_text`` is the written data file, if any (checks formatting);
    ``imports`` are the repo's import statements per module (see ``module_imports``), so names
    a package re-exports count as existing; ``index`` (the target repo's) lets the checks
    follow reuse: inherited tests, and helpers or tests the test calls in base classes."""
    subject = Subject(
        generated, settings, catalog, first_party or [], draft, data_text, imports or {}
    )
    subject.index = index
    report = ValidationReport(checks_run=["syntax"])
    report.findings += list(check_syntax(subject))
    if subject.tree is None:
        return report
    _prepare(subject)
    for name, check in CHECKS:
        report.checks_run.append(name)
        report.findings += list(check(subject))
    return report


def chain_analysis(
    generated: GeneratedTest, index: IndexData, settings: Settings
) -> dict[str, FunctionChains]:
    """The validator's chain analysis of a generated test (test name -> chains), for code that
    needs the missing members themselves rather than error messages (gaps/)."""
    subject = Subject(generated, settings, index.catalog, [], None, None, {})
    subject.index = index
    if next(iter(check_syntax(subject)), None) is not None or subject.tree is None:
        return {}
    _prepare(subject)
    return dict(subject.chains)


def _is_testcase(cls: ast.ClassDef, bases: list[ClassEntry], testcase: list[str]) -> bool:
    """The class inherits unittest.TestCase: itself, or a repo base up its lineage."""
    names = set(testcase) | {t.rsplit(".", 1)[-1] for t in testcase}
    written = [dotted(b) for b in cls.bases] + [w for b in bases for w in b.bases]
    return any(w in names or w.rsplit(".", 1)[-1] in names for w in written)


def _prepare(s: Subject) -> None:
    assert s.tree is not None
    v, d = s.settings.validation, s.settings.data
    s.base = next(  # where chains start when a class's own bases aren't in the repo
        (
            c
            for c in (s.catalog.class_named(b) for b in suite_base_classes(s.catalog, s.settings))
            if c is not None
        ),
        None,
    )
    s.tests = test_functions(
        s.tree, s.settings.index.test_function_prefix, s.settings.index.test_class_prefix
    )
    helpers = set(d.expectation_sections.values())
    module = PurePosixPath(s.generated.file_name).with_suffix("").as_posix().replace("/", ".")
    reuse = Resolver(s.tree, module, s.index, d.access, helpers)
    s.resolver = reuse
    prefix = s.settings.index.test_function_prefix
    s.uses = dict(data_use(s.code, d.access, list(helpers), prefix))  # module-level tests
    for cls, fn in s.tests:
        local = class_local_members(cls) if cls else set()
        bases = reuse.repo_bases(cls) if cls else []
        start = bases[0] if bases else s.base  # the class's own base, else the suite's
        s.chains[fn.name] = function_chains(fn, ChainResolver(s.catalog, start, local))
        self_asserts = cls is not None and _is_testcase(cls, bases, v.testcase_bases)
        s.checks[fn.name] = check_calls(fn, v.assertion_object, helpers, self_asserts)
        if cls is not None:
            s.uses[fn.name] = reuse.data_use(cls, fn)
            s.deep_checks[fn.name] = reuse.checks_through_calls(
                cls, fn, v.assertion_object, self_asserts
            )
    for cls in reuse.classes():
        if not cls.name.startswith(s.settings.index.test_class_prefix):
            continue
        for test in reuse.inherited_tests(cls, prefix):
            s.inherited_ids += test.ids
            method = reuse.method(cls, test.name)
            if method is not None:
                s.uses[test.name] = reuse.data_use(cls, method)


def _strings(value: Any) -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            found.add(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)

    walk(value)
    return found


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
