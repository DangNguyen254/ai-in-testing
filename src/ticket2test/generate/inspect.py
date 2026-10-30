"""Static inspection of generated code. The code is parsed, never run.

Tree-sitter computes pytest ids; ``ast`` finds how tests use their data entry.
"""

from __future__ import annotations

import ast
import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass, field

from ticket2test.index.extract import FunctionInfo, ParseError, extract_file
from ticket2test.index.pytest_ids import compute_test_ids


def computed_test_ids(
    code: str, test_prefix: str = "test", class_prefix: str = "Test"
) -> list[str]:
    """Pytest names the code would produce. Raises ValueError with a message for the LLM."""
    try:
        info = extract_file("generated.py", code.encode("utf-8"))
    except ParseError as exc:
        raise ValueError(f"the code does not parse: {exc}") from exc

    ids: list[str] = []
    problems: list[str] = []
    tests: list[tuple[FunctionInfo, list[str]]] = [
        (fn, []) for fn in info.functions if fn.name.startswith(test_prefix)
    ]
    for cls in info.classes:
        if cls.name.startswith(class_prefix):
            tests += [(m, cls.decorators) for m in cls.methods if m.name.startswith(test_prefix)]
    for fn, class_decorators in tests:
        result = compute_test_ids(fn.name, fn.decorators, class_decorators)
        if not result.computed:
            problems.append(f"{fn.name}: {result.note}")
        ids.extend(result.names)
    if problems:
        raise ValueError(
            "parametrize values must be literals so the ids are known before running: "
            + "; ".join(problems)
        )
    if not ids:
        raise ValueError(
            f"no test found: define a method named {test_prefix}_... in a class named "
            f"{class_prefix}..."
        )
    return ids


@dataclass(frozen=True)
class DataUse:
    """How one test function uses its data entry."""

    keys: frozenset[str]  # keys indexed directly: params["key"]
    optional_keys: frozenset[str]  # params.get("key", ...), or indexed only after a check
    helpers: frozenset[str]  # entry-reading helpers it calls
    passes_whole: bool = False  # hands the whole entry to a call: which keys it reads is unknown
    # What the class's setup/teardown read and call: consumed for the test, never required,
    # and not a sign that the test itself reads its entry.
    hook_keys: frozenset[str] = frozenset()
    hook_helpers: frozenset[str] = frozenset()

    @property
    def reads_data(self) -> bool:
        return bool(self.keys or self.optional_keys or self.helpers)


def data_use(
    code: str, access: list[str], helpers: list[str], test_prefix: str = "test"
) -> dict[str, DataUse]:
    """Per test function: which entry keys it reads and which entry-reading helpers it calls.

    ``access`` are the expressions a test indexes (``self.params``, ``params``); ``helpers``
    are calls that read the entry for the test (``self.validate_backend``).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"the code does not parse: {exc}") from exc
    roots = set(access)
    found: dict[str, DataUse] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith(test_prefix):
            continue
        reads = entry_reads(
            (n for statement in node.body for n in ast.walk(statement)), roots, helpers
        )
        found[node.name] = reads.use()
    return found


def helper_matches(name: str, patterns: Iterable[str]) -> bool:
    """``name`` (a dotted call) is one of the helper names, or matches one with ``*``."""
    return any(name == p or ("*" in p and fnmatch.fnmatchcase(name, p)) for p in patterns)


@dataclass
class EntryReads:
    """What a function body does with the entry, before calls to other methods are followed."""

    keys: set[str] = field(default_factory=set)
    optional: set[str] = field(default_factory=set)
    guarded: set[str] = field(default_factory=set)  # "key" in params / params.get("key")
    helpers: set[str] = field(default_factory=set)
    self_calls: set[str] = field(default_factory=set)
    passes_whole: bool = False
    # Calls that hand the entry or ``self`` to another function: (callee, argument position or
    # keyword, the root or "self"). The resolver follows those it finds in the repo.
    passed: list[tuple[str, int | str, str]] = field(default_factory=list)
    # ``Base.setup(self)`` and ``super().setup()``: (the class named, or "super"; the method)
    base_calls: set[tuple[str, str]] = field(default_factory=set)
    # names used as the key (``self.params[user]``): the function's parameters among them read
    # the key their callers pass, or the parameter's default
    key_names: set[str] = field(default_factory=set)
    # ``self.<method>(...)`` calls: (method, positional arguments, keyword arguments)
    self_call_sites: list[tuple[str, list[ast.expr], dict[str, ast.expr]]] = field(
        default_factory=list
    )

    def add(self, other: EntryReads) -> None:
        self.keys |= other.keys
        self.optional |= other.optional
        self.guarded |= other.guarded
        self.helpers |= other.helpers
        self.passes_whole = self.passes_whole or other.passes_whole

    def use(self) -> DataUse:
        """Keys only indexed after a check on them are optional."""
        soft = self.guarded | self.optional
        return DataUse(
            frozenset(self.keys - soft),
            frozenset(self.optional | (self.keys & soft)),
            frozenset(self.helpers),
            self.passes_whole,
        )


def entry_reads(nodes: Iterable[ast.AST], roots: set[str], helpers: Iterable[str]) -> EntryReads:
    patterns = list(helpers)
    reads = EntryReads()
    nodes = list(nodes)
    aliases = _aliases(nodes, roots)
    rebound = _rebound(nodes, roots)
    tried = _in_key_error_try(nodes)
    all_roots = roots
    for node in nodes:
        line = getattr(node, "lineno", 0)  # after a rebinding line the name is something else
        direct = all_roots - {r for r, at in rebound.items() if line > at}
        roots = direct | {a for a, at in aliases.items() if line > at}
        if isinstance(node, ast.Subscript) and _dotted(node.value) in roots:
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                reads.keys.add(node.slice.value)
                if _dotted(node.value) not in direct:  # through a copy: read, not required
                    reads.optional.add(node.slice.value)
                if id(node) in tried:  # try: params["k"] ... except KeyError: a missing key
                    reads.guarded.add(node.slice.value)
            elif isinstance(node.slice, ast.Name):
                reads.key_names.add(node.slice.id)
        elif isinstance(node, ast.Compare) and _key_check(node, roots):
            reads.guarded.add(node.left.value)  # type: ignore[attr-defined]
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if helper_matches(name, patterns):
                reads.helpers.add(name)
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and _dotted(node.func.value) in roots
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                reads.optional.add(node.args[0].value)
            elif name.startswith("self.") and name.count(".") == 1:
                reads.self_calls.add(name.removeprefix("self."))
                reads.self_call_sites.append(
                    (
                        name.removeprefix("self."),
                        list(node.args),
                        {k.arg: k.value for k in node.keywords if k.arg},
                    )
                )
            elif _is_super_call(node.func):
                reads.base_calls.add(("super", node.func.attr))  # type: ignore[attr-defined]
            elif (
                isinstance(node.func, ast.Attribute)
                and node.args
                and _dotted(node.args[0]) == "self"
                and _dotted(node.func.value)
            ):
                reads.base_calls.add((_dotted(node.func.value), node.func.attr))
            given: list[tuple[int | str, ast.expr]] = [
                *enumerate(node.args),
                *((k.arg, k.value) for k in node.keywords if k.arg),
            ]
            for where, arg in given:
                passed = _dotted(arg)
                if passed in roots:
                    reads.passes_whole = True  # e.g. runner.run(self.params)
                    reads.passed.append((name, where, passed))
                elif passed == "self" and name and not name.startswith("self."):
                    reads.passed.append((name, where, "self"))  # e.g. check_policy(self)
    return reads


def _is_super_call(func: ast.expr) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Call)
        and isinstance(func.value.func, ast.Name)
        and func.value.func.id == "super"
    )


_KEY_ERRORS = {"KeyError", "LookupError", "Exception", "BaseException"}


def _in_key_error_try(nodes: list[ast.AST]) -> set[int]:
    """Ids of the nodes in the body of a ``try`` whose handlers catch a missing key."""
    found: set[int] = set()
    for node in nodes:
        if not isinstance(node, ast.Try):
            continue
        caught: set[str] = set()
        for handler in node.handlers:
            kinds = handler.type
            items = kinds.elts if isinstance(kinds, ast.Tuple) else [kinds]
            caught |= {"Exception"} if kinds is None else {_dotted(k) for k in items if k}
        if caught & _KEY_ERRORS:
            found |= {id(n) for statement in node.body for n in ast.walk(statement)}
    return found


def _rebound(nodes: list[ast.AST], roots: set[str]) -> dict[str, int]:
    """Bare-name roots the function assigns itself (``params = params["block"]``), with the
    first line that does: reads through them after it are of something else, not the entry."""
    found: dict[str, int] = {}
    for node in nodes:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        if isinstance(node, ast.For):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in roots:
                found[target.id] = min(found.get(target.id, target.lineno), target.lineno)
    return found


def _aliases(nodes: list[ast.AST], roots: set[str]) -> dict[str, int]:
    """Local names that may hold the entry, a copy or a part of it, from the line that assigns
    them: ``data = self.params``, ``row = resolve(env, params)``. What is read through them
    counts as read, never as required (a part's keys aren't the entry's)."""
    found: dict[str, int] = {}
    for node in nodes:
        if not isinstance(node, ast.Assign) or not _copies_entry(node.value, roots):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):  # params = get(params, ...) too: maybe a part
                found[target.id] = min(found.get(target.id, target.lineno), target.lineno)
    return found


def _copies_entry(value: ast.expr, roots: set[str]) -> bool:
    """The entry itself, or a call given the entry (a copy or a resolved version of it)."""
    if _dotted(value) in roots:
        return True
    return isinstance(value, ast.Call) and any(
        _dotted(arg) in roots for arg in [*value.args, *(k.value for k in value.keywords)]
    )


def _key_check(node: ast.Compare, roots: set[str]) -> bool:
    """``"key" in params`` or ``"key" not in params``."""
    return (
        isinstance(node.left, ast.Constant)
        and isinstance(node.left.value, str)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.In | ast.NotIn)
        and _dotted(node.comparators[0]) in roots
    )


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else ""
    return node.id if isinstance(node, ast.Name) else ""


def defined_names(code: str, test_prefix: str = "test", class_prefix: str = "Test") -> list[str]:
    """Names of the test classes and test functions the code defines."""
    tree = ast.parse(code)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            prefix = class_prefix
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            prefix = test_prefix
        else:
            continue
        if node.name.startswith(prefix):
            names.append(node.name)
    return names
