"""Static analysis of a generated test module (``ast``; the code is never run).

The main job is resolving attribute chains through the symbol catalog: ``self.nav.rules.list``
from the suite's base class, and local variables bound to such a chain
(``rules = self.nav.rules.list`` then ``rules.total_count``), with the kind of every step
(property, method, attribute) and whether it was called or assigned.
"""

from __future__ import annotations

import ast
import builtins
import fnmatch
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from ticket2test.generate.inspect import helper_matches
from ticket2test.index.catalog import ClassEntry, MemberKind, SymbolCatalog

ChainStatus = Literal["ok", "missing", "unknown_type"]


def dotted(node: ast.expr) -> str:
    """``self.nav.rules`` -> "self.nav.rules"; "" for anything that isn't names and dots."""
    if isinstance(node, ast.Attribute):
        inner = dotted(node.value)
        return f"{inner}.{node.attr}" if inner else ""
    return node.id if isinstance(node, ast.Name) else ""


def test_functions(
    tree: ast.Module, test_prefix: str, class_prefix: str
) -> list[tuple[ast.ClassDef | None, ast.FunctionDef]]:
    """Test functions pytest would collect: module-level and in test classes, in order."""
    found: list[tuple[ast.ClassDef | None, ast.FunctionDef]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith(test_prefix):
            found.append((None, node))
        elif isinstance(node, ast.ClassDef) and node.name.startswith(class_prefix):
            found += [
                (node, item)
                for item in node.body
                if isinstance(item, ast.FunctionDef) and item.name.startswith(test_prefix)
            ]
    return found


def test_classes(tree: ast.Module, class_prefix: str) -> list[ast.ClassDef]:
    return [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith(class_prefix)]


def markers(decorators: list[ast.expr]) -> dict[str, list[str]]:
    """``@pytest.mark.priority("p2")`` -> {"priority": ["p2"]} (string arguments only)."""
    found: dict[str, list[str]] = {}
    for decorator in decorators:
        call = decorator if isinstance(decorator, ast.Call) else None
        name = dotted(call.func if call else decorator)
        if not name.startswith("pytest.mark.") or name.count(".") != 2:
            continue
        values = found.setdefault(name.rsplit(".", 1)[1], [])
        if call:
            values += [
                a.value
                for a in call.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
    return found


def pytestmark_nodes(body: list[ast.stmt]) -> list[ast.expr]:
    """The marks of ``pytestmark = ...`` in a module or class body (one mark or a list)."""
    found: list[ast.expr] = []
    for node in body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            value = node.value
            found += list(value.elts) if isinstance(value, ast.List | ast.Tuple) else [value]
    return found


def docstring(fn: ast.FunctionDef) -> str:
    return ast.get_docstring(fn) or ""


def bound_names(tree: ast.Module) -> set[str]:
    """Every name the module binds anywhere, plus builtins (scopes are not separated)."""
    names = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__package__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            names.add(node.id)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            names.update(node.names)
    return names


# --- attribute chains -----------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    name: str
    called: bool  # the step is called: ``x.open()``
    kind: MemberKind | None = None  # None once the chain leaves the catalog
    owner: str | None = None  # class qualname that has the member


@dataclass
class ChainUse:
    root: str  # "self" or a local variable
    steps: list[Step]
    line: int
    store: bool  # the last step is assigned to: ``wizard.name = ...``
    status: ChainStatus = "ok"
    message: str = ""
    missing_owner: str | None = None  # status "missing": the class that lacks the member

    @property
    def text(self) -> str:
        return ".".join([self.root, *(s.name + ("()" if s.called else "") for s in self.steps)])


@dataclass
class FunctionChains:
    uses: list[ChainUse] = field(default_factory=list)
    local_types: dict[str, str] = field(default_factory=dict)  # variable -> class qualname


def _chain_of(node: ast.Attribute) -> tuple[str, list[tuple[str, bool]]] | None:
    """``a.b().c`` -> ("a", [("b", True), ("c", False)]). None if not rooted at a name."""
    steps: list[tuple[str, bool]] = []
    current: ast.expr = node
    called = False
    while True:
        if isinstance(current, ast.Attribute):
            steps.insert(0, (current.attr, called))
            called = False
            current = current.value
        elif isinstance(current, ast.Call):
            called = True
            current = current.func
        elif isinstance(current, ast.Name):
            return (current.id, steps) if not called else None
        else:
            return None


class ChainResolver:
    """Resolves chains against the catalog, starting at the base class or a known type."""

    def __init__(
        self,
        catalog: SymbolCatalog,
        base_class: ClassEntry | None,
        local: set[str],
        path_helpers: set[str] | None = None,
        other_bases: list[ClassEntry] | None = None,
    ):
        self.catalog = catalog
        self.base = base_class
        # the class's further repo bases (``class T(Mixin, Base)``): ``self`` has their members too
        self.other_bases = other_bases or []
        self.local = local  # members the generated class defines itself
        self.path_helpers = path_helpers or set()  # helpers taking a dotted page path string

    def path_type(self, call: ast.Call) -> str | None:
        """The page a path-string helper returns: ``go_to("area.page")`` -> the class at
        ``<root>.area.page``. None when it isn't such a call or the path doesn't resolve."""
        name = dotted(call.func).rsplit(".", 1)[-1]
        if name not in self.path_helpers or not call.args:
            return None
        arg = call.args[0]
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            return None
        text = arg.value.strip().strip(".")
        roots = list(self.catalog.chain_roots)
        tries = [text] if text.split(".")[0] in roots else [f"{r}.{text}" for r in roots]
        for chain in tries:
            result = self.catalog.resolve_chain_from_roots(chain)
            if result.ok and result.types and result.types[-1]:
                return result.types[-1]
        return None

    def resolve(
        self, root: str, raw: list[tuple[str, bool]], start: str | None
    ) -> tuple[ChainStatus, list[Step], str, str | None]:
        """(status, steps with kinds, message, type after the last step)."""
        owner = self.catalog.classes.get(start) if start else None
        steps: list[Step] = []
        for index, (name, called) in enumerate(raw):
            if owner is None:
                steps += [Step(n, c) for n, c in raw[index:]]
                return "unknown_type", steps, "", None
            found = self.catalog.member(owner.qualname, name)
            if found is None and self.catalog.external_bases(owner.qualname):
                steps += [Step(n, c) for n, c in raw[index:]]  # may come from outside the repo
                return "unknown_type", steps, "", None
            if found is None:
                steps += [Step(n, c) for n, c in raw[index:]]
                prefix = ".".join([root, *(n for n, _ in raw[:index])])
                message = f"{prefix} ({owner.name}) has no member {name!r}"
                return "missing", steps, message, owner.qualname  # the owner, not a type
            defined_in, member = found
            steps.append(Step(name, called, member.kind, owner.qualname))
            # Annotation, built class, ``return self``, or ``return self.nav.area.page``.
            next_type: ClassEntry | None = self.catalog._member_type(defined_in, member, owner)
            owner = next_type
        return "ok", steps, "", owner.qualname if owner else None

    def resolve_self(
        self, root: str, raw: list[tuple[str, bool]]
    ) -> tuple[ChainStatus, list[Step], str, str | None]:
        """A ``self`` chain: through the first base, else through whichever further base has
        the member (the first result stands when none does)."""
        first = self.resolve(root, raw, self.base.qualname if self.base else None)
        if first[0] != "missing":
            return first
        for other in self.other_bases:
            found = self.resolve(root, raw, other.qualname)
            if found[0] != "missing":
                return found
        return first


def function_chains(
    fn: ast.FunctionDef, resolver: ChainResolver, roots: set[str] | None = None
) -> FunctionChains:
    """All chains rooted at ``self`` or at a local bound to a resolved chain, in source order."""
    result = FunctionChains()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Assign):
            visit(node.value)
            for target in node.targets:
                visit(target)
            value = node.value
            page = resolver.path_type(value) if isinstance(value, ast.Call) else None
            if (
                page is not None
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                result.local_types[node.targets[0].id] = page  # ``x = self.go_to("area.page")``
                return
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                value = value.func  # ``editor = self.open_exception(name)``: the return type
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(value, ast.Attribute)
            ):
                use = _record(value, store=False, collect=False)
                if use is not None and use[1]:
                    result.local_types[node.targets[0].id] = use[1]
                else:
                    result.local_types.pop(node.targets[0].id, None)
            return
        if isinstance(node, ast.Attribute):
            _record(node, store=isinstance(node.ctx, ast.Store), collect=True)
            # Arguments of calls inside the chain still need visiting.
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    for arg in [*inner.args, *(k.value for k in inner.keywords)]:
                        visit(arg)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    def _record(
        node: ast.Attribute, store: bool, collect: bool
    ) -> tuple[ChainUse, str | None] | None:
        chain = _chain_of(node)
        if chain is None:
            return None
        root, raw = chain
        if root == "self":
            if not raw or raw[0][0] in resolver.local:
                return None
            start = None
        elif root in result.local_types:
            start = result.local_types[root]
        elif roots is not None and root in roots:
            start = None
        else:
            return None
        called_last = _is_called(node)
        raw = [*raw[:-1], (raw[-1][0], raw[-1][1] or called_last)]
        if root == "self":
            status, steps, message, last_type = resolver.resolve_self(root, raw)
        else:
            status, steps, message, last_type = resolver.resolve(root, raw, start)
        use = ChainUse(root, steps, node.lineno, store, status, message)
        if status == "missing":
            use.missing_owner, last_type = last_type, None
        if collect:
            result.uses.append(use)
        return use, last_type

    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(fn):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    def _is_called(node: ast.Attribute) -> bool:
        parent = parents.get(id(node))
        return isinstance(parent, ast.Call) and parent.func is node

    for statement in fn.body:
        visit(statement)
    return result


def class_local_members(cls: ast.ClassDef) -> set[str]:
    """Methods and ``self.x = ...`` attributes the generated class defines itself."""
    names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    for node in ast.walk(cls):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                names.add(node.attr)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


# --- checks (assertions and validation helpers) ----------------------------------------------


@dataclass(frozen=True)
class CheckCall:
    method: str  # "assertEqual", or the helper's dotted name
    helper: bool  # an expectation-section helper (verify_targets ...)
    node: ast.Call

    @property
    def line(self) -> int:
        return self.node.lineno


def check_calls(
    fn: ast.FunctionDef,
    assertion_object: str | list[str],
    helpers: set[str],
    self_asserts: bool = False,
    check_helpers: list[str] | tuple[str, ...] = (),
) -> list[CheckCall]:
    """Assertions on the assertion object, validation-helper calls, calls whose name matches
    ``check_helpers`` (the suite's own checking helpers, e.g. ``verify_*``), and (in a class
    that inherits ``unittest.TestCase``) ``self.assert*`` / ``self.fail*``."""
    found: list[CheckCall] = []
    for node in _walk_in_order(fn):
        if not isinstance(node, ast.Call):
            continue
        name = dotted(node.func)
        if helper_matches(name, helpers) or is_check_helper(name, check_helpers):
            found.append(CheckCall(name, True, node))
        elif is_assertion(name, assertion_object, self_asserts):
            found.append(CheckCall(name.rsplit(".", 1)[1], False, node))
    return found


def is_check_helper(name: str, patterns: list[str] | tuple[str, ...]) -> bool:
    """The called name's last part matches one of the suite's check-helper patterns."""
    last = name.rsplit(".", 1)[-1]
    return bool(last) and any(fnmatch.fnmatchcase(last, p) for p in patterns)


def is_assertion(name: str, assertion_object: str | list[str], self_asserts: bool) -> bool:
    objects = [assertion_object] if isinstance(assertion_object, str) else assertion_object
    if any(name.startswith(o + ".") and name.count(".") == o.count(".") + 1 for o in objects):
        return True
    method = name.removeprefix("self.")
    return (
        self_asserts
        and name.startswith("self.")
        and "." not in method
        and (method.startswith(("assert", "fail")))
    )


def _walk_in_order(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _walk_in_order(child)
