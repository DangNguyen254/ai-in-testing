"""Which keys inside an entry section a test reads, when the test reads the section itself.

``target = self.params["targets"][0]`` then ``self.driver.get(target["url"])`` and
``self._verify_log(target)``: the test reads ``targets`` itself, so each key of its items must be
read by the test or by a helper it hands the item to. Followed: subscripts and ``.get`` with a
string key, ``"key" in x``, aliases (``x = section[0]``, ``for x in section``), and
``self.<method>`` calls given the section or an item (into the method, through its parameter;
also in repo base classes). Any other use (a call that can't be followed, iteration over keys,
a comparison of the whole item) means the whole section is used: ``None``, nothing is judged.

Also the self methods the test calls are scanned for their own reads of the section
(``self.params["targets"]`` in a helper), so a key read there isn't taken for unread.
"""

from __future__ import annotations

import ast
from typing import Any

from ticket2test.validate.code import dotted
from ticket2test.validate.datause import Resolver

SectionReads = dict[str, set[str] | None]  # section -> keys read in it; None: used whole

_MAX_DEPTH = 3  # helper -> helper -> helper
_MAX_METHODS = 40


def section_reads(
    fn: ast.FunctionDef, cls: ast.ClassDef | None, resolver: Resolver | None, access: list[str]
) -> SectionReads:
    """Per section the function (and the self methods it calls) reads itself: its keys read."""
    found: SectionReads = {}
    queue: list[tuple[ast.FunctionDef, dict[str, str], int]] = [(fn, {}, 0)]
    scanned: set[tuple[int, tuple[tuple[str, str], ...]]] = set()
    while queue and len(scanned) < _MAX_METHODS:
        function, params, depth = queue.pop()
        key = (id(function), tuple(sorted(params.items())))
        if key in scanned:
            continue
        scanned.add(key)
        for callee, given, used in _scan(function, params, set(access)):
            for section, keys in used.items():
                _merge(found, section, keys)
            if callee is None:
                continue
            method = resolver.method(cls, callee) if resolver and cls else None
            if method is None:
                for section in given.values():
                    _merge(found, section, None)  # handed to something not followed
            elif depth < _MAX_DEPTH:
                queue.append((method, _bind(method, given), depth + 1))
            else:
                for section in given.values():
                    _merge(found, section, None)
    return found


def call_reads(
    call: ast.Call,
    cls: ast.ClassDef | None,
    resolver: Resolver | None,
    sections: dict[str, str],
    access: list[str],
) -> dict[str, set[str] | None]:
    """For a ``self.<method>(...)`` call: per local (``sections``: local -> section) it is
    given, the section keys the method reads through it (None: unknown, the whole)."""
    name = dotted(call.func)
    if not name.startswith("self.") or name.count(".") != 1:
        return {}
    method = resolver.method(cls, name.removeprefix("self.")) if resolver and cls else None
    given: dict[int | str, str] = {}
    pairs: list[tuple[int | str, ast.expr]] = [
        *enumerate(call.args),
        *((k.arg, k.value) for k in call.keywords if k.arg),
    ]
    for where, arg in pairs:
        if isinstance(arg, ast.Name) and arg.id in sections:
            given[where] = arg.id
    if not given:
        return {}
    if method is None:
        return {local: None for local in given.values()}
    result: dict[str, set[str] | None] = {}
    for where, local in given.items():
        param = _param(method, where)
        if param is None:
            result[local] = None
            continue
        reads = section_reads_from(method, {param: sections[local]}, cls, resolver, access)
        result[local] = reads.get(sections[local], set())
    return result


def section_reads_from(
    function: ast.FunctionDef,
    params: dict[str, str],
    cls: ast.ClassDef | None,
    resolver: Resolver | None,
    access: list[str],
) -> SectionReads:
    """``section_reads`` for a method whose parameters ``params`` hold sections."""
    found: SectionReads = {}
    for callee, given, used in _scan(function, params, set(access)):
        for section, keys in used.items():
            _merge(found, section, keys)
        if callee is None:
            continue
        method = resolver.method(cls, callee) if resolver and cls else None
        if method is None or not given:
            for section in given.values():
                _merge(found, section, None)
            continue
        for section, keys in section_reads_from(
            method, _bind(method, given), cls, resolver, access
        ).items():
            if section in given.values():
                _merge(found, section, keys)
    return found


def subkeys(value: Any) -> set[str]:
    """Keys of a section's value: a dict's, or those of the dicts in a list."""
    if isinstance(value, dict):
        return set(value)
    if isinstance(value, list):
        return {k for item in value if isinstance(item, dict) for k in item}
    return set()


def without_keys(value: Any, keys: set[str]) -> Any:
    """The section's value without ``keys`` (in a dict, or in each dict of a list)."""
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [without_keys(item, keys) if isinstance(item, dict) else item for item in value]
    return value


def consumed_elsewhere(
    use: Any,
    seed_sections: list[str],
    per_entry_keys: list[str],
    convention_keys: list[str],
    expectations: dict[str, list[str]],
) -> set[str] | None:
    """Sections whose keys aren't the test's to read: seeds, per-entry and convention keys, keys
    setup/teardown read, expectation sections whose helper is called. None: the entry is handed
    whole to something (any key may be read)."""
    from ticket2test.generate.inspect import helper_matches

    if use is None or getattr(use, "passes_whole", False):
        return None
    helpers = set(use.helpers) | set(getattr(use, "hook_helpers", frozenset()))
    called = {
        section
        for section, patterns in expectations.items()
        if any(helper_matches(h, patterns) for h in helpers)
    }
    hooks = set(getattr(use, "hook_keys", frozenset()))
    return {*seed_sections, *per_entry_keys, *convention_keys, *hooks, *called}


def unread_subkeys(
    entry: dict[str, Any], reads: SectionReads, skip: set[str]
) -> dict[str, set[str]]:
    """Per section the test reads itself (not in ``skip``: consumed elsewhere too), its keys
    nothing reads."""
    found: dict[str, set[str]] = {}
    for section, keys in reads.items():
        if keys is None or section in skip or section not in entry:
            continue
        unread = subkeys(entry[section]) - keys
        if unread:
            found[section] = unread
    return found


# --- one function --------------------------------------------------------------------------


def _merge(into: SectionReads, section: str, keys: set[str] | None) -> None:
    if section in into and into[section] is None:
        return
    if keys is None:
        into[section] = None
        return
    current = into.setdefault(section, set())
    assert current is not None
    current.update(keys)


def _param(method: ast.FunctionDef, where: int | str) -> str | None:
    names = [a.arg for a in [*method.args.posonlyargs, *method.args.args]][1:]  # no self
    if isinstance(where, int):
        return names[where] if where < len(names) else None
    kwonly = [a.arg for a in method.args.kwonlyargs]
    return where if where in names or where in kwonly else None


def _bind(method: ast.FunctionDef, given: dict[int | str, str]) -> dict[str, str]:
    """Call arguments (position or keyword -> section) as the method's parameter names."""
    bound: dict[str, str] = {}
    for where, section in given.items():
        param = _param(method, where)
        if param is not None:
            bound[param] = section
    return bound


def _strip_items(node: ast.expr) -> ast.expr:
    """``x[0]`` / ``x[-1]`` -> ``x``: an item of a list section is the section's shape."""
    while (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant | ast.UnaryOp)
        and not (isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str))
    ):
        node = node.value
    return node


def _scan(
    function: ast.FunctionDef, params: dict[str, str], roots: set[str]
) -> list[tuple[str | None, dict[int | str, str], dict[str, set[str] | None]]]:
    """(self method called or None, its arguments holding sections, section keys read here)."""
    parents: dict[int, ast.AST] = {}
    for outer in ast.walk(function):
        for child in ast.iter_child_nodes(outer):
            parents[id(child)] = outer
    local: dict[str, str] = dict(params)

    def section_of(node: ast.expr) -> str | None:
        node = _strip_items(node)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            return local.get(node.id)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
            and dotted(node.value) in roots
        ):
            return node.slice.value
        return None

    for _ in range(3):  # aliases of aliases
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                section = section_of(node.value)
                if isinstance(target, ast.Name) and section is not None:
                    local[target.id] = section
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                section = section_of(node.iter)
                if section is not None:
                    local[node.target.id] = section

    used: dict[str, set[str] | None] = {}
    calls: dict[int, tuple[str, dict[int | str, str]]] = {}
    self_calls = {
        id(n): dotted(n.func).removeprefix("self.")
        for n in ast.walk(function)
        if isinstance(n, ast.Call)
        and dotted(n.func).startswith("self.")
        and dotted(n.func).count(".") == 1
    }
    for node in ast.walk(function):
        if not isinstance(node, ast.Name | ast.Subscript):
            continue
        if isinstance(node, ast.Name) and (
            not isinstance(node.ctx, ast.Load) or node.id not in local
        ):
            continue
        if isinstance(node, ast.Subscript):
            if not (
                isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
                and dotted(node.value) in roots
            ):
                continue
            section = node.slice.value
        else:
            section = local[node.id]
        expr: ast.AST = node
        parent: ast.AST | None = parents.get(id(expr))
        while (  # an item of the section: x[0]
            isinstance(parent, ast.Subscript)
            and parent.value is expr
            and not (isinstance(parent.slice, ast.Constant) and isinstance(parent.slice.value, str))
            and isinstance(parent.slice, ast.Constant | ast.UnaryOp)
        ):
            expr, parent = parent, parents.get(id(parent))
        keys: set[str] | None
        if (
            isinstance(parent, ast.Subscript)
            and parent.value is expr
            and isinstance(parent.slice, ast.Constant)
            and isinstance(parent.slice.value, str)
        ):
            keys = {parent.slice.value}
        elif (
            isinstance(parent, ast.Attribute)
            and parent.attr == "get"
            and isinstance(parents.get(id(parent)), ast.Call)
        ):
            call = parents[id(parent)]
            assert isinstance(call, ast.Call)
            first = call.args[0] if call.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                keys = {first.value}
            else:
                keys = None
        elif (
            isinstance(parent, ast.Compare)
            and parent.comparators
            and parent.comparators[0] is expr
            and isinstance(parent.ops[0], ast.In | ast.NotIn)
            and isinstance(parent.left, ast.Constant)
            and isinstance(parent.left.value, str)
        ):
            keys = {parent.left.value}
        elif isinstance(parent, ast.Assign) and parent.value is expr:
            alias = parent.targets[0] if len(parent.targets) == 1 else None
            keys = set() if isinstance(alias, ast.Name) and alias.id in local else None
        elif isinstance(parent, ast.For) and parent.iter is expr:
            keys = set() if isinstance(parent.target, ast.Name) else None
        elif isinstance(parent, ast.Call) and id(parent) in self_calls and expr is not parent.func:
            where: int | str | None = next(
                (i for i, a in enumerate(parent.args) if a is expr),
                next((k.arg for k in parent.keywords if k.value is expr and k.arg), None),
            )
            if where is None:
                keys = None
            else:
                name = self_calls[id(parent)]
                calls.setdefault(id(parent), (name, {}))[1][where] = section
                keys = set()
        else:
            keys = None
        if keys is None:
            used[section] = None
        elif used.get(section, set()) is not None:
            current = used.setdefault(section, set())
            assert current is not None
            current.update(keys)
    result: list[tuple[str | None, dict[int | str, str], dict[str, set[str] | None]]] = [
        (None, {}, used)
    ]
    handed = {i for i in calls}
    result += [(name, given, {}) for name, given in calls.values()]
    # self methods called without a section: still scanned for their own reads of it
    result += [(name, {}, {}) for i, name in self_calls.items() if i not in handed]
    return result
