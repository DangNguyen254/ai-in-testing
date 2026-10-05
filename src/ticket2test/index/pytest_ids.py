"""Static computation of pytest test ids from ``@pytest.mark.parametrize`` decorators.

Mirrors pytest's IdMaker (``_pytest/python.py``) for statically known values:
- ``pytest.param(..., id=...)``, then ``ids=[...]``, then a value-derived id
- str/bytes are ASCII-escaped; None/int/float/bool/complex use ``str()``;
  anything else becomes ``<argname><index>``
- duplicate ids get a counter (``_`` before it if the id ends in a digit)
- stacked decorators: marks apply bottom-up, so the bottom decorator's id comes first;
  class-level parametrize ids follow the function's

Only literals are evaluated (``ast.literal_eval``), never code. Anything else (names,
calls, ``ids=`` callables, parametrized fixtures, a custom ``pytest_make_parametrize_id``
hook) makes the result "not computed": the real ids then come from ``pytest --collect-only``.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

_NON_PRINTABLE = {i: f"\\x{i:02x}" for i in range(128) if i not in range(32, 127)}
_NON_PRINTABLE.update({ord("\t"): "\\t", ord("\r"): "\\r", ord("\n"): "\\n"})


class NotStatic(ValueError):
    """The decorator can't be evaluated without running code."""


@dataclass
class ParametrizeInfo:
    source: str
    argnames: list[str]
    ids: list[str] | None  # None when not statically computable
    note: str | None = None


@dataclass
class TestIds:
    __test__ = False  # not a pytest test class

    names: list[str]  # e.g. ["test_x[1-a]", ...]; just ["test_x"] when not parametrized
    computed: bool = True
    note: str | None = None
    decorators: list[ParametrizeInfo] = field(default_factory=list)  # source order


def ascii_escaped(value: str | bytes) -> str:
    if isinstance(value, bytes):
        text = value.decode("ascii", "backslashreplace")
    else:
        text = value.encode("unicode_escape").decode("ascii")
    return text.translate(_NON_PRINTABLE)


def is_parametrize(decorator: str) -> bool:
    head = decorator.split("(", 1)[0].strip()
    return head.endswith("mark.parametrize") or head == "parametrize"


def compute_test_ids(
    function_name: str,
    function_decorators: list[str],
    class_decorators: list[str] | None = None,
    param_names: list[str] | None = None,
    parametrized_fixtures: frozenset[str] = frozenset(),
    custom_id_hook: bool = False,
) -> TestIds:
    """Compute pytest names for a test function. Decorators are given in source order."""
    infos = [_parse(d) for d in function_decorators if is_parametrize(d)]
    class_infos = [_parse(d) for d in (class_decorators or []) if is_parametrize(d)]
    all_infos = infos + class_infos

    fixture_hits = sorted(set(param_names or []) & parametrized_fixtures)
    problems = [i.note for i in all_infos if i.ids is None and i.note]
    if fixture_hits:
        problems.append(f"uses parametrized fixture(s): {', '.join(fixture_hits)}")
    if custom_id_hook and all_infos:
        problems.append("a pytest_make_parametrize_id hook may change the ids")
    if problems:
        return TestIds([function_name], computed=False, note="; ".join(problems), decorators=infos)
    if not all_infos:
        return TestIds([function_name], decorators=infos)

    # Apply in pytest's order: function decorators bottom-up, then class decorators bottom-up.
    combined = [""]
    for info in [*reversed(infos), *reversed(class_infos)]:
        assert info.ids is not None
        combined = [f"{prefix}-{i}" if prefix else i for prefix in combined for i in info.ids]
    return TestIds([f"{function_name}[{c}]" for c in combined], decorators=infos)


# --- one decorator -------------------------------------------------------------------------


def _parse(decorator: str) -> ParametrizeInfo:
    try:
        argnames, ids = _evaluate(decorator)
    except NotStatic as exc:
        names = _argnames_only(decorator)
        return ParametrizeInfo(decorator, names, None, f"{decorator.split('(')[0]}: {exc}")
    return ParametrizeInfo(decorator, argnames, ids)


def _argnames_only(decorator: str) -> list[str]:
    try:
        call = _call(decorator)
        return _argnames(call.args[0]) if call.args else []
    except (NotStatic, SyntaxError, ValueError):
        return []


def _call(decorator: str) -> ast.Call:
    node = ast.parse(decorator, mode="eval").body
    if not isinstance(node, ast.Call):
        raise NotStatic("not a call")
    return node


def _argnames(node: ast.expr) -> list[str]:
    value = _literal(node)
    if isinstance(value, str):
        return [n.strip() for n in value.split(",") if n.strip()]
    if isinstance(value, list | tuple) and all(isinstance(v, str) for v in value):
        return [str(v) for v in value]
    raise NotStatic("argnames must be a string or a list of strings")


def _literal(node: ast.expr) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
        raise NotStatic(f"non-literal value {ast.unparse(node)[:60]!r}") from exc


def _evaluate(decorator: str) -> tuple[list[str], list[str]]:
    try:
        call = _call(decorator)
    except SyntaxError as exc:
        raise NotStatic("unparsable decorator") from exc
    keywords = {k.arg: k.value for k in call.keywords if k.arg}
    argnames_node = call.args[0] if call.args else keywords.get("argnames")
    values_node = call.args[1] if len(call.args) > 1 else keywords.get("argvalues")
    if argnames_node is None or values_node is None:
        raise NotStatic("missing argnames or argvalues")
    argnames = _argnames(argnames_node)
    if not isinstance(values_node, ast.List | ast.Tuple):
        raise NotStatic("argvalues is not a literal list")

    ids_list: list[Any] | None = None
    if "ids" in keywords:
        ids_value = _literal(keywords["ids"])  # a callable here raises NotStatic
        if not isinstance(ids_value, list | tuple):
            raise NotStatic("ids is not a literal list")
        ids_list = list(ids_value)

    resolved: list[str] = []
    for idx, element in enumerate(values_node.elts):
        values, explicit_id = _parameter_set(element, len(argnames))
        if explicit_id is not None:
            resolved.append(ascii_escaped(str(explicit_id)))
        elif ids_list is not None and idx < len(ids_list) and ids_list[idx] is not None:
            id_value = _idval_from_value(ids_list[idx])
            if id_value is None:
                raise NotStatic(f"unsupported ids value at index {idx}")
            resolved.append(id_value)
        else:
            parts = []
            for value, argname in zip(values, argnames, strict=True):
                id_value = _idval_from_value(value)
                parts.append(id_value if id_value is not None else f"{argname}{idx}")
            resolved.append("-".join(parts))
    if not resolved:
        raise NotStatic("empty argvalues")
    return argnames, _make_unique(resolved)


def _parameter_set(element: ast.expr, n_argnames: int) -> tuple[list[Any], Any]:
    """Values and explicit id of one argvalues element (plain value or ``pytest.param``)."""
    if isinstance(element, ast.Call) and _is_pytest_param(element.func):
        values = [_literal(arg) for arg in element.args]
        explicit_id = None
        for keyword in element.keywords:
            if keyword.arg == "id":
                explicit_id = _literal(keyword.value)
        if len(values) != n_argnames:
            raise NotStatic("pytest.param value count doesn't match argnames")
        return values, explicit_id
    value = _literal(element)
    if n_argnames == 1:
        return [value], None
    if not isinstance(value, list | tuple) or len(value) != n_argnames:
        raise NotStatic("value count doesn't match argnames")
    return list(value), None


def _is_pytest_param(func: ast.expr) -> bool:
    if isinstance(func, ast.Attribute):
        return func.attr == "param"
    return isinstance(func, ast.Name) and func.id == "param"


def _idval_from_value(value: Any) -> str | None:
    if isinstance(value, str | bytes):
        return ascii_escaped(value)
    if value is None or isinstance(value, float | int | bool | complex):
        return str(value)
    return None  # literal containers etc. fall back to <argname><idx>


def _make_unique(ids: list[str]) -> list[str]:
    counts = Counter(ids)
    if len(counts) == len(ids):
        return ids
    suffixes: dict[str, int] = defaultdict(int)
    result = list(ids)
    taken = set(ids)
    for index, value in enumerate(ids):
        if counts[value] > 1:
            sep = "_" if value and value[-1].isdigit() else ""
            new = f"{value}{sep}{suffixes[value]}"
            while new in taken:
                suffixes[value] += 1
                new = f"{value}{sep}{suffixes[value]}"
            result[index] = new
            suffixes[value] += 1
    return result
