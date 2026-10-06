"""Static inspection of generated code. The code is parsed, never run.

Tree-sitter computes pytest ids; ``ast`` finds how tests use their data entry.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

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
    optional_keys: frozenset[str]  # params.get("key", ...)
    helpers: frozenset[str]  # entry-reading helpers it calls

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
    roots, helper_names = set(access), set(helpers)
    found: dict[str, DataUse] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith(test_prefix):
            continue
        keys: set[str] = set()
        optional: set[str] = set()
        called: set[str] = set()
        for inner in (n for statement in node.body for n in ast.walk(statement)):
            if isinstance(inner, ast.Subscript) and _dotted(inner.value) in roots:
                if isinstance(inner.slice, ast.Constant) and isinstance(inner.slice.value, str):
                    keys.add(inner.slice.value)
            elif isinstance(inner, ast.Call):
                name = _dotted(inner.func)
                if name in helper_names:
                    called.add(name)
                elif (
                    isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "get"
                    and _dotted(inner.func.value) in roots
                    and inner.args
                    and isinstance(inner.args[0], ast.Constant)
                    and isinstance(inner.args[0].value, str)
                ):
                    optional.add(inner.args[0].value)
        found[node.name] = DataUse(frozenset(keys), frozenset(optional), frozenset(called))
    return found


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
