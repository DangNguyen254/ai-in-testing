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
from collections.abc import Iterator
from dataclasses import dataclass, field

from ticket2test.generate.inspect import DataUse
from ticket2test.index.catalog import ClassEntry, SymbolCatalog
from ticket2test.index.extract import ClassInfo, FileInfo
from ticket2test.index.indexer import IndexData
from ticket2test.index.pytest_ids import compute_test_ids
from ticket2test.validate.code import dotted

_MAX_METHODS = 200  # bound on methods followed per test


@dataclass
class _Reads:
    keys: set[str] = field(default_factory=set)
    optional: set[str] = field(default_factory=set)
    helpers: set[str] = field(default_factory=set)
    self_calls: set[str] = field(default_factory=set)


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

    def data_use(self, cls: ast.ClassDef, function: ast.FunctionDef) -> DataUse:
        """Keys and helpers the function uses, following ``self.<method>()`` calls."""
        total = _Reads()
        seen: set[str] = set()
        queue = [function]
        while queue and len(seen) < _MAX_METHODS:
            current = queue.pop()
            if current.name in seen:
                continue
            seen.add(current.name)
            reads = self._reads(current)
            total.keys |= reads.keys
            total.optional |= reads.optional
            total.helpers |= reads.helpers
            for name in reads.self_calls - seen:
                found = self.method(cls, name)
                if found is not None:
                    queue.append(found)
        return DataUse(frozenset(total.keys), frozenset(total.optional), frozenset(total.helpers))

    def checks_through_calls(
        self, cls: ast.ClassDef, function: ast.FunctionDef, assertion_object: str
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
                dotted(n.func).startswith(assertion_object + ".")
                for n in _walk(method)
                if isinstance(n, ast.Call)
            ):
                return True
            queue += list(reads.self_calls - seen)
        return False

    def _reads(self, function: ast.FunctionDef) -> _Reads:
        reads = _Reads()
        for node in _walk(function):
            if isinstance(node, ast.Subscript) and dotted(node.value) in self.access:
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    reads.keys.add(node.slice.value)
            elif isinstance(node, ast.Call):
                name = dotted(node.func)
                if name in self.helpers:
                    reads.helpers.add(name)
                elif (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and dotted(node.func.value) in self.access
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    reads.optional.add(node.args[0].value)
                elif name.startswith("self.") and name.count(".") == 1:
                    reads.self_calls.add(name.removeprefix("self."))
        return reads


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
