"""Deterministic validators for a generated test (code + data entries).

Each check returns findings; ``error`` findings block the test (and feed the repair loop),
``warning`` findings are heuristics for the reviewer. Nothing here runs the generated code.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from ticket2test.config import Settings
from ticket2test.generate.entries import function_of
from ticket2test.generate.inspect import DataUse, computed_test_ids, data_use
from ticket2test.index.catalog import ClassEntry, SymbolCatalog, import_map
from ticket2test.index.chunks import is_test_file
from ticket2test.index.datafile import merged, split_defaults
from ticket2test.index.indexer import IndexData
from ticket2test.index.tokens import split_identifier
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import GeneratedTest, _name_problems, _unconsumed_keys
from ticket2test.security.masking import TOKEN
from ticket2test.security.private import MARK, PrivateTerms
from ticket2test.style import format_entries
from ticket2test.style.local import detect_json_style, detect_python_style
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
    def module(self) -> str:
        """The module name the file has in the repo."""
        return PurePosixPath(self.generated.file_name).with_suffix("").as_posix().replace("/", ".")

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
                    if alias.name == "*":  # binds what the module defines (check_names)
                        continue
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
    """Plain names must be bound somewhere in the module (imports, definitions, locals). A
    star import binds what its module defines; from a module outside the repo it could bind
    anything, so a name not found is then only a warning."""
    assert s.tree is not None
    bound = bound_names(s.tree)
    unknown_star = ""
    for star in _star_modules(s):
        names, known = s.catalog.star_names(star)
        bound |= names
        if not known:
            unknown_star = unknown_star or star
    for node in ast.walk(s.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
            if unknown_star:
                yield _f(
                    "names",
                    f"name {node.id!r} isn't defined here; it may come from "
                    f"'from {unknown_star} import *', which can't be checked",
                    "warning",
                    line=node.lineno,
                )
            else:
                yield _f("names", f"undefined name {node.id!r}", line=node.lineno)


_HOOK_UNSAFE = re.compile(r"""['"\\\n{}]""")


def check_risky_patterns(s: Subject) -> Iterator[Finding]:
    """Reviewer warnings for patterns static checks can't judge but real suites trip on: a
    test calling another test, state shared between tests, broad ``except`` (it can hide the
    failure the test is for), marker or per-entry values with characters hooks that build code
    from them choke on, and new entries identical to their template (copied values)."""
    assert s.tree is not None
    prefix = s.settings.index.test_function_prefix
    for _, fn in s.tests:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr.startswith(prefix)
                ):
                    yield _f(
                        "risky",
                        f"calls another test, self.{node.func.attr}(): it then depends on that "
                        "test's state and order; call the shared steps through a helper",
                        "warning",
                        test=fn.name,
                        line=node.lineno,
                    )
            elif isinstance(node, ast.Global):
                yield _f(
                    "risky",
                    f"changes module globals ({', '.join(node.names)}): state shared between "
                    "tests makes them depend on run order",
                    "warning",
                    test=fn.name,
                    line=node.lineno,
                )
            elif isinstance(node, ast.Assign) and any(_is_class_state(t) for t in node.targets):
                yield _f(
                    "risky",
                    "sets class-level state from a test: later tests in the class see it",
                    "warning",
                    test=fn.name,
                    line=node.lineno,
                )
            elif isinstance(node, ast.ExceptHandler) and _broad(node):
                yield _f(
                    "risky",
                    "a broad except can hide the very failure this test should report; catch "
                    "the specific exception, or let it fail",
                    "warning",
                    test=fn.name,
                    line=node.lineno,
                )
    for cls, fn in s.tests:
        for decorator in [*(cls.decorator_list if cls else []), *fn.decorator_list]:
            if not isinstance(decorator, ast.Call) or not dotted(decorator.func).startswith(
                "pytest.mark."
            ):
                continue
            for arg in decorator.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and _HOOK_UNSAFE.search(arg.value)
                ):
                    yield _f(
                        "risky",
                        f"marker value {arg.value!r} has quotes, braces or backslashes; hooks "
                        "that build code from marker values can break on it",
                        "warning",
                        line=decorator.lineno,
                    )
    d = s.settings.data
    for entry in s.entries:
        for key in d.per_entry_keys:
            value = entry.get(key)
            if isinstance(value, str) and _HOOK_UNSAFE.search(value):
                yield _f(
                    "risky",
                    f"{key!r} value {value!r} has quotes, braces or backslashes; hooks that "
                    "build code from entry values can break on it",
                    "warning",
                    test=str(entry.get(d.id_field, "")),
                )
    yield from _copied_entries(s)


def _is_class_state(target: ast.expr) -> bool:
    """``self.__class__.x = ...``, ``type(self).x = ...``, ``cls.x = ...``."""
    if not isinstance(target, ast.Attribute):
        return False
    owner = target.value
    if isinstance(owner, ast.Attribute) and owner.attr == "__class__":
        return True
    if isinstance(owner, ast.Call) and dotted(owner.func) == "type":
        return True
    return isinstance(owner, ast.Name) and owner.id == "cls"


def _broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = [handler.type] if not isinstance(handler.type, ast.Tuple) else handler.type.elts
    return any(dotted(n) in ("Exception", "BaseException") for n in names)


def _copied_entries(s: Subject) -> Iterator[Finding]:
    """A new entry equal to its template entry except for the id: its values were copied, not
    chosen for the ticket."""
    ref = s.generated.template_entry_ref
    if ref is None or s.index is None:
        return
    chunk = next((c for c in s.index.chunks if c.id == ref.chunk_id), None)
    template = chunk.data_entries.get(ref.entry_key) if chunk else None
    if not isinstance(template, dict):
        return
    id_field = s.settings.data.id_field
    new = set(s.generated.new_test_ids) or set(s.generated.test_ids)
    plain = {k: v for k, v in template.items() if k != id_field}
    for entry in s.entries:
        test_id = str(entry.get(id_field, ""))
        same = {k: v for k, v in entry.items() if k != id_field} == plain
        if test_id in new and test_id != ref.entry_key and same:
            yield _f(
                "risky",
                f"the entry is a copy of {ref.entry_key} apart from its id: check that its "
                "values fit this ticket",
                "warning",
                test=test_id,
            )


def check_star_imports(s: Subject) -> Iterator[Finding]:
    """New code imports the names it uses: a star import hides them from every name check."""
    assert s.tree is not None
    for node in s.tree.body:
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            yield _f(
                "star_imports",
                f"'from {node.module or '.'} import *': import the names you use instead",
                line=node.lineno,
            )


def _star_modules(s: Subject) -> list[str]:
    return s.catalog.star_imports.get(s.module, [])


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


_UNITTEST_HOOKS = {"setUp": "setup", "tearDown": "teardown", "setUpClass": "setup",
                   "tearDownClass": "teardown"}  # fmt: skip
_FRAMEWORK_HOOKS = ("setup", "teardown")


def check_hooks(s: Subject) -> Iterator[Finding]:
    """A setup/teardown hook nothing will call, so the class's setup silently doesn't run
    (real suites mix setup, setup_method and setUp). pytest always calls setup_method /
    setup_class; unittest's setUp runs only in a ``unittest.TestCase`` class; a plain
    ``setup`` runs only when something up the lineage calls it (a base defines it)."""
    if s.resolver is None or s.tree is None:
        return
    v = s.settings.validation
    for cls in test_classes(s.tree, s.settings.index.test_class_prefix):
        bases = s.resolver.repo_bases(cls)
        defined = {n for b in bases for n in b.members}
        testcase = _is_testcase(cls, bases, v.testcase_bases)
        for node in cls.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            name, role = node.name, _UNITTEST_HOOKS.get(node.name)
            if role and not testcase:
                instead = role if role in defined else f"{role}_method"
                yield _f(
                    "hooks",
                    f"{cls.name}.{name} runs only in a unittest.TestCase class, and this class "
                    f"isn't one: define {instead} instead",
                    "warning",
                    line=node.lineno,
                )
            elif name in _FRAMEWORK_HOOKS and name not in defined:
                yield _f(
                    "hooks",
                    f"{cls.name}.{name}: nothing up the class's lineage calls {name}; "
                    f"define {name}_method instead (pytest calls it)",
                    "warning",
                    line=node.lineno,
                )


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


_CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]*$")


def check_page_locators(s: Subject) -> Iterator[Finding]:
    """Tests use page-object actions and properties, never the page objects' locator constants
    (``editor.click(editor.CLEAR_EXPIRY)``). A test that needs an action the page object lacks
    should call it by name: the name check then reports it, and the gap finder records it."""
    if not s.settings.validation.forbid_page_locators:
        return
    page_objects = set(s.catalog.page_objects)
    constants = {
        name
        for q in page_objects
        if (entry := s.catalog.classes.get(q)) is not None
        for name, member in entry.members.items()
        if member.kind == "attribute" and _CONSTANT.match(name)
    }
    if not constants:
        return
    for _, fn in s.tests:
        reported: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute) and node.attr in constants:
                text = dotted(node)
                if text in reported:
                    continue
                reported.add(text)
                yield _f(
                    "page_locators",
                    f"{text} is a page object's locator: use the page's actions and "
                    "properties; if the action you need doesn't exist, call it by the name it "
                    "would have (it is then reported as a missing piece)",
                    test=fn.name,
                    line=node.lineno,
                )


def check_raw_driver(s: Subject) -> Iterator[Finding]:
    """UI tests drive the browser through page objects, never the raw driver
    (``self.driver.get(url)``): a second way around a missing page action, found on the held-out
    v6 set. As with locators, the action should be called by name so the gap is reported."""
    raw = s.settings.validation.raw_driver_access
    if not raw:
        return
    for _, fn in s.tests:
        reported: set[str] = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Attribute):
                continue
            text = dotted(node)
            base = next((r for r in raw if text == r or text.startswith(r + ".")), None)
            if base is None or base in reported:
                continue
            reported.add(base)
            yield _f(
                "raw_driver",
                f"{text} uses the browser driver directly: go through the page objects; if the "
                "action or value you need doesn't exist, call it by the name it would have (it "
                "is then reported as a missing piece)",
                test=fn.name,
                line=node.lineno,
            )


def check_constructed_pages(s: Subject) -> Iterator[Finding]:
    """Pages come from the chain root or a path-string helper. Building one with its
    constructor (``LoginPage(driver)``) is allowed only where the test's existing class already
    builds that page, and is then flagged for the reviewer; anywhere else it is an error."""
    simple = {q.rsplit(".", 1)[-1] for q in s.catalog.page_objects}
    if not simple:
        return
    for cls, fn in s.tests:
        existing = _class_code(s, cls)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            name = dotted(node.func).rsplit(".", 1)[-1]
            if name not in simple:
                continue
            if existing and re.search(rf"\b{re.escape(name)}\(", existing):
                yield _f(
                    "constructed_pages",
                    f"{name}(...) builds the page directly, as {cls.name if cls else 'the class'} "
                    "already does: confirm it is the same page state the chain root would give",
                    severity="warning",
                    test=fn.name,
                    line=node.lineno,
                )
            else:
                yield _f(
                    "constructed_pages",
                    f"{name}(...) builds a page directly: reach it through the chain root or a "
                    "path-string helper (a constructor is allowed only where the existing class "
                    "already builds that page)",
                    test=fn.name,
                    line=node.lineno,
                )


def _class_code(s: Subject, cls: ast.ClassDef | None) -> str:
    """The indexed (existing) source of the test's class, "" for a new class."""
    record = s.index.files.get(s.generated.file_name) if s.index and cls else None
    if record is None or record.info is None or cls is None:
        return ""
    return next((c.code for c in record.info.classes if c.name == cls.name), "")


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

    def parts(values: Iterable[str]) -> set[str]:
        sep = m.value_separator
        return {p.strip() for v in values for p in (v.split(sep) if sep else [v]) if p.strip()}

    allowed: dict[str, set[str]] = {
        "priority": set(m.priorities),
        "suite": set(m.suites),
        "project": parts([m.project, *s.catalog.markers.get("project", [])]),
        "component": parts(s.catalog.markers.get("component", [])),
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
            for value in sorted(parts(values)) if name in ("project", "component") else values:
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
    """The code is a fixed point of the formatter: in the configured style, or (with
    ``style.follow_local``) in the indent and quotes the file itself uses."""
    style = s.settings.style.python
    code = s.code
    if s.settings.style.follow_local:
        style = detect_python_style(code, style)
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
        "allowed_expectation_sets": d.allowed_expectation_sets,
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


def _name_helper(s: Subject, cls: ast.ClassDef | None) -> str:
    """The unique-name helper the class's lineage provides (``validation.unique_name_helpers``,
    first match from the class itself up), else ``validation.unique_name_helper``."""
    v = s.settings.validation
    if cls is None or not v.unique_name_helpers:
        return v.unique_name_helper
    names = [cls.name, *(dotted(b).rsplit(".", 1)[-1] for b in cls.bases)]
    if s.resolver is not None:
        names += [entry.name for entry in s.resolver.repo_bases(cls)]
    return next(
        (v.unique_name_helpers[n] for n in names if n in v.unique_name_helpers),
        v.unique_name_helper,
    )


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
    style = s.settings.style.json_files
    if s.settings.style.follow_local:
        style = detect_json_style(s.data_text, style)
    expected = format_entries(written, d, style, s.generated.data_format)
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
    assert s.tree is not None
    known = {v.unique_name_helper, *v.unique_name_helpers.values()}
    for cls, fn in s.tests:
        helper = _name_helper(s, cls)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            name = dotted(node.func)
            if name in known and name != helper:
                yield _f(
                    "names_unique",
                    f"{name}() belongs to another base class; this class's base provides "
                    f"{helper}()",
                    line=node.lineno,
                    test=fn.name,
                )
            elif name == helper and node.args:
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
    helper = v.unique_name_helper
    for node in ast.walk(s.tree):
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
    ("page_locators", check_page_locators),
    ("raw_driver", check_raw_driver),
    ("star_imports", check_star_imports),
    ("risky", check_risky_patterns),
    ("constructed_pages", check_constructed_pages),
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
    statements = [
        ast.get_source_segment(s.code, node) or ""
        for node in s.tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    names, stars = import_map(statements, s.module)  # names resolve through this file's imports
    s.catalog = s.catalog.model_copy(
        update={
            "module_names": {**s.catalog.module_names, s.module: names},
            "star_imports": {**s.catalog.star_imports, s.module: stars},
        }
    )
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
    path_helpers = path_string_helpers(s.index, s.settings)
    for cls, fn in s.tests:
        local = class_local_members(cls) if cls else set()
        bases = reuse.repo_bases(cls) if cls else []
        start = bases[0] if bases else s.base  # the class's own base, else the suite's
        resolver = ChainResolver(s.catalog, start, local, path_helpers)
        s.chains[fn.name] = function_chains(fn, resolver)
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
