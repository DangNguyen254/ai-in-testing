"""How tests use their data entry, following reuse: helpers, tests calling tests, inheritance.

A test reads its entry directly (``self.params["k"]``, ``self.params.get("k")``) or through
methods it calls on ``self``: helpers and other tests, defined in the same class or inherited
from the repo's base classes. A class also collects the tests it inherits. This module
resolves both with the symbol catalog and the indexed sources, so the data checks see every
key the test really reads.
"""

from __future__ import annotations

import ast
import textwrap
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace

from ticket2test.generate.inspect import DataUse, EntryReads, entry_reads
from ticket2test.index.catalog import ClassEntry, SymbolCatalog
from ticket2test.index.extract import ClassInfo, FileInfo, FunctionInfo
from ticket2test.index.indexer import IndexData
from ticket2test.index.pytest_ids import compute_test_ids
from ticket2test.validate.code import dotted, is_assertion, is_check_helper

_MAX_METHODS = 200  # bound on methods followed per test
_MAX_PASS_DEPTH = 2  # functions the entry is handed to, then the ones they hand it to


@dataclass(frozen=True)
class InheritedTest:
    name: str
    ids: list[str]
    computed: bool


class Resolver:
    """Finds method bodies: in the module's own classes, then in the repo's base classes."""

    def __init__(
        self,
        tree: ast.Module,
        module: str,
        index: IndexData | None,
        access: list[str],
        helpers: set[str],
    ) -> None:
        self.tree = tree
        self.module = module
        self.index = index
        self.catalog: SymbolCatalog | None = index.catalog if index else None
        self.infos = {
            path: record.info
            for path, record in (index.files.items() if index else [])
            if record.info is not None
        }
        self.access = set(access)
        self.helpers = helpers
        self._parsed: dict[tuple[str, str], ast.ClassDef | None] = {}
        self._hooked: dict[tuple[str, tuple[str, ...]], EntryReads] = {}
        self._functions: dict[str, FunctionInfo] | None = None  # qualname -> module function
        self._handed: dict[tuple[str, frozenset[str], int], EntryReads | None] = {}

    # --- classes and their bases -------------------------------------------------------

    def classes(self) -> list[ast.ClassDef]:
        return [n for n in self.tree.body if isinstance(n, ast.ClassDef)]

    def repo_bases(self, cls: ast.ClassDef) -> list[ClassEntry]:
        """The class's bases that exist in the repo, each with its own bases (MRO order)."""
        if self.catalog is None:
            return []
        found: list[ClassEntry] = []
        for base in cls.bases:
            entry = self.catalog.resolve_type(dotted(base), self.module)
            if entry is not None:
                found += [e for e in self.catalog.mro(entry.qualname) if e not in found]
        return found

    def inherited_tests(self, cls: ast.ClassDef, test_prefix: str) -> list[InheritedTest]:
        own = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        class_decorators = [ast.unparse(d) for d in cls.decorator_list]
        found: list[InheritedTest] = []
        for base in self.repo_bases(cls):
            _, base_cls = self._class_info(base)
            if base_cls is None:
                continue
            for method in base_cls.methods:
                if not method.name.startswith(test_prefix) or method.name in own:
                    continue
                own.add(method.name)
                params = [p.name for p in method.params if p.name not in ("self", "cls")]
                result = compute_test_ids(
                    method.name,
                    method.decorators,
                    [*class_decorators, *base_cls.decorators],
                    params,
                )
                found.append(InheritedTest(method.name, result.names, result.computed))
        return found

    # --- method bodies ----------------------------------------------------------------

    def method(self, cls: ast.ClassDef, name: str) -> ast.FunctionDef | None:
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        for base in self.repo_bases(cls):
            _, base_cls = self._class_info(base)
            if base_cls is None or not any(m.name == name for m in base_cls.methods):
                continue
            key = (base.file_path, base.name)
            if key not in self._parsed:  # base classes are shared by every test: parse once
                self._parsed[key] = _parse_class(base_cls)
            parsed = self._parsed[key]
            if parsed is not None:
                return next(
                    (n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == name),
                    None,
                )
        return None

    def _class_info(self, entry: ClassEntry) -> tuple[FileInfo | None, ClassInfo | None]:
        info = self.infos.get(entry.file_path)
        if info is None:
            return None, None
        return info, next((c for c in info.classes if c.name == entry.name), None)

    # --- data use ---------------------------------------------------------------------

    def data_use(
        self, cls: ast.ClassDef, function: ast.FunctionDef, hooks: Iterable[str] = ()
    ) -> DataUse:
        """Keys and helpers the function uses, following ``self.<method>()`` calls. ``hooks``:
        the class's setup/teardown methods (its own or inherited), which run for every test,
        so the keys they read and the helpers they call count as consumed (``hook_keys``,
        ``hook_helpers``). Their passing the whole entry on doesn't: a base setup that hands it
        to seeding would make every key look consumed."""
        total = EntryReads()
        seen: set[str] = set()
        self._follow(cls, [function], seen, total)
        key = (cls.name, (*hooks, *self.autouse_fixtures(cls)))
        if key not in self._hooked:  # the same for every test of the class
            hooked = EntryReads()
            found = [self.method(cls, name) for name in key[1]]
            self._follow(cls, [f for f in found if f is not None], set(), hooked)
            self._hooked[key] = hooked
        hooked = self._hooked[key]
        return replace(
            total.use(),
            hook_keys=frozenset(hooked.keys | hooked.optional),
            hook_helpers=frozenset(hooked.helpers),
        )

    def _follow(
        self, cls: ast.ClassDef, queue: list[ast.FunctionDef], seen: set[str], total: EntryReads
    ) -> None:
        """Adds what the methods (and the ``self.<method>()`` calls they make) read to
        ``total``."""
        while queue and len(seen) < _MAX_METHODS:
            current = queue.pop()
            if current.name in seen:
                continue
            seen.add(current.name)
            reads = self._reads(current)
            total.add(reads)
            for name in reads.self_calls - seen:
                found = self.method(cls, name)
                if found is not None:
                    queue.append(found)

    def checks_through_calls(
        self,
        cls: ast.ClassDef,
        function: ast.FunctionDef,
        assertion_object: str | list[str],
        self_asserts: bool = False,
        check_helpers: list[str] | tuple[str, ...] = (),
        hooks: Iterable[str] = (),
    ) -> bool:
        """True if a method the function calls (transitively) asserts or validates, or a
        teardown of the class does (checks that run after every test)."""
        seen = {function.name}
        after = [h for h in hooks if "teardown" in h.lower()]
        queue = [*after, *self._reads(function).self_calls]
        while queue and len(seen) < _MAX_METHODS:
            name = queue.pop()
            if name in seen:
                continue
            seen.add(name)
            method = self.method(cls, name)
            if method is None:
                continue
            reads = self._reads(method)
            if reads.helpers or any(
                is_assertion(dotted(n.func), assertion_object, self_asserts)
                or is_check_helper(dotted(n.func), check_helpers)
                for n in _walk(method)
                if isinstance(n, ast.Call)
            ):
                return True
            queue += list(reads.self_calls - seen)
        return False

    def autouse_fixtures(self, cls: ast.ClassDef) -> list[str]:
        """Methods of the class or its repo bases that are autouse pytest fixtures: they run
        around every test, like setup/teardown."""
        found = [
            n.name
            for n in cls.body
            if isinstance(n, ast.FunctionDef)
            and any(_is_autouse(ast.unparse(d)) for d in n.decorator_list)
        ]
        for base in self.repo_bases(cls):
            _, base_cls = self._class_info(base)
            for method in base_cls.methods if base_cls else []:
                if any(_is_autouse(d) for d in method.decorators) and method.name not in found:
                    found.append(method.name)
        return found

    def _reads(self, function: ast.FunctionDef) -> EntryReads:
        reads = entry_reads(_walk(function), self.access, self.helpers)
        return self._with_handed(reads, depth=0)

    def _with_handed(self, reads: EntryReads, depth: int) -> EntryReads:
        """Adds what repo functions read when the entry (or ``self``) is handed to them. A
        call that can't be followed keeps ``passes_whole``; when all can, it is dropped."""
        if not reads.passed or depth >= _MAX_PASS_DEPTH:
            return reads
        unresolved = False
        for callee, where, given in reads.passed:
            found = self._handed_reads(callee, where, given, depth)
            if found is None:
                unresolved = unresolved or given != "self"
                continue
            reads.add(found)
        if not unresolved:
            reads.passes_whole = False
        return reads

    def _handed_reads(
        self, callee: str, where: int | str, given: str, depth: int
    ) -> EntryReads | None:
        function = self._module_function(callee)
        if function is None:
            return None
        params = [p.name for p in function.params]
        if isinstance(where, int):
            param = params[where] if where < len(params) else None
        else:
            param = where if where in params else None
        if param is None:
            return None
        if given == "self":  # self.params -> <param>.params
            roots = {f"{param}{a[len('self') :]}" for a in self.access if a.startswith("self.")}
        else:
            roots = {param}
        key = (callee, frozenset(roots), depth)
        if key not in self._handed:
            self._handed[key] = None  # a function that hands the entry to itself stops here
            tree = _parse_function(function)
            if tree is not None:
                reads = entry_reads(_walk(tree), roots, self.helpers)
                reads.passes_whole = bool(reads.passed) and reads.passes_whole
                self._handed[key] = self._with_handed(reads, depth + 1)
        return self._handed[key]

    def _module_function(self, callee: str) -> FunctionInfo | None:
        """The repo's module-level function a call names, through the module's imports."""
        if self.catalog is None:
            return None
        if self._functions is None:
            self._functions = {
                f"{info.module}.{fn.name}": fn
                for info in self.infos.values()
                for fn in info.functions
            }
        head, _, rest = callee.partition(".")
        target = self.catalog.imported(self.module, head) or f"{self.module}.{head}"
        return self._functions.get(f"{target}.{rest}" if rest else target)


def _is_autouse(decorator: str) -> bool:
    return "fixture" in decorator and "autouse=True" in decorator.replace(" ", "")


def _parse_function(function: FunctionInfo) -> ast.FunctionDef | None:
    try:
        tree = ast.parse(textwrap.dedent(function.code))
    except SyntaxError:
        return None
    node = tree.body[0] if tree.body else None
    return node if isinstance(node, ast.FunctionDef) else None


def _parse_class(cls: ClassInfo) -> ast.ClassDef | None:
    """The class's source as a syntax tree (its code starts at column 0)."""
    try:
        tree = ast.parse(textwrap.dedent(cls.code))
    except SyntaxError:
        return None
    node = tree.body[0] if tree.body else None
    return node if isinstance(node, ast.ClassDef) else None


def _walk(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _walk(child)
