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
from ticket2test.index.extract import ClassInfo, FileInfo
from ticket2test.index.indexer import IndexData
from ticket2test.index.pytest_ids import compute_test_ids
from ticket2test.validate.code import dotted, is_assertion, is_check_helper

_MAX_METHODS = 200  # bound on methods followed per test


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
            parsed = _parse_class(base_cls)
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
        hooked = EntryReads()
        found = [self.method(cls, name) for name in hooks]
        self._follow(cls, [f for f in found if f is not None], seen, hooked)
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
        assertion_object: str,
        self_asserts: bool = False,
        check_helpers: list[str] | tuple[str, ...] = (),
    ) -> bool:
        """True if a method the function calls (transitively) asserts or validates."""
        seen = {function.name}
        queue = [n for n in self._reads(function).self_calls]
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

    def _reads(self, function: ast.FunctionDef) -> EntryReads:
        return entry_reads(_walk(function), self.access, self.helpers)


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
