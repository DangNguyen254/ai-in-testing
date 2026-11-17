"""The usage table: what the suite's tests call, in order, and what the framework defines.

Built by code from the syntax of the index's files: no model, no type resolution needed to
record a call. It answers "the tests of this class (this folder) do this step by calling
that", which a word search can't: a helper is found by where it is used, not by its name.

- **Per test:** its ``self`` calls in source order, as written (``self.`` dropped), with a
  local bound to a ``self`` chain read as that chain (``rules = self.nav.rules.list`` then
  ``rules.open()`` is ``nav.rules.list.open``). The assertion objects' calls are left out.
- **Per call, in a scope** (the tests of one class, or of one folder): how many tests make it,
  where in their sequence it usually comes (0 first, 1 last), one example as written, and,
  when the catalog can type it, the class that defines it.
- **The framework:** every function and method outside the test files, with its owner,
  signature, the first line of its docstring and the ``self`` calls it makes itself. It covers
  what no test calls yet (a new area's pages).

Computed from an index on demand and kept per index, so it is always in step with it.
"""

from __future__ import annotations

import ast
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ticket2test.config import Settings
from ticket2test.index.chunks import is_test_file
from ticket2test.index.extract import FunctionInfo
from ticket2test.index.indexer import IndexData
from ticket2test.models.chunk import Chunk


@dataclass(frozen=True)
class CallUse:
    """One call as a scope's tests make it."""

    call: str  # as written, ``self.`` dropped: "nav.rules.list.open", "verify_targets"
    tests: int  # how many tests of the scope make it
    position: float  # where in a test's sequence, on average: 0 first, 1 last
    example: str  # one call as written, arguments included (cut)
    defined_in: str | None  # the class that defines it, when the catalog can type it


@dataclass(frozen=True)
class Definition:
    """A function or method outside the test files."""

    owner: str  # the class name, "" for a module function
    name: str
    signature: str  # "(self, name, scope=None)"
    doc: str  # the first line of the docstring, "" when none
    file_path: str
    line: int
    calls: tuple[str, ...]  # its own ``self`` calls, in order


@dataclass
class UsageTable:
    sequences: dict[str, list[str]] = field(default_factory=dict)  # test chunk id -> calls
    examples: dict[str, dict[str, str]] = field(default_factory=dict)  # chunk id -> call -> text
    definitions: list[Definition] = field(default_factory=list)
    _tests: dict[str, Chunk] = field(default_factory=dict)

    def scope(
        self, index: IndexData, file_path: str | None = None, class_name: str | None = None,
        folder: str | None = None, exclude: set[str] | None = None,
    ) -> list[CallUse]:  # fmt: skip
        """The calls of the tests of one class (``file_path`` + ``class_name``) or of one
        ``folder`` (directly in it), most used first. ``exclude``: test chunk ids left out."""
        chosen = [
            c
            for c in self._tests.values()
            if c.id not in (exclude or set())
            and (
                (c.file_path == file_path and c.class_name == class_name)
                if file_path is not None
                else c.file_path.rpartition("/")[0] == (folder or "")
            )
        ]
        count: Counter[str] = Counter()
        where: dict[str, list[float]] = defaultdict(list)
        example: dict[str, str] = {}
        owner_class: dict[str, str | None] = {}
        for chunk in chosen:
            calls = self.sequences.get(chunk.id, [])
            for call in dict.fromkeys(calls):
                count[call] += 1
                first = calls.index(call)
                where[call].append(first / (len(calls) - 1) if len(calls) > 1 else 0.0)
                example.setdefault(call, self.examples.get(chunk.id, {}).get(call, call))
                if call not in owner_class:
                    owner_class[call] = defined_in(call, chunk.class_name, index)
        return [
            CallUse(
                call=call,
                tests=n,
                position=round(sum(where[call]) / len(where[call]), 2),
                example=example[call],
                defined_in=owner_class[call],
            )
            for call, n in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))
        ]


def defined_in(call: str, class_name: str | None, index: IndexData) -> str | None:
    """The class that defines the call's last member, followed from the test's class the way
    its ``self`` resolves; None when the catalog can't type the chain."""
    catalog = index.catalog
    owner = catalog.class_named(class_name) if class_name else None
    if owner is None:
        return None
    *steps, member = call.removesuffix("()").split(".")
    if steps:
        resolution = catalog.resolve_chain(owner.qualname, [s.removesuffix("()") for s in steps])
        last = resolution.types[-1] if resolution.ok and resolution.types else None
        owner = catalog.classes.get(last) if last else None
        if owner is None:
            return None
    found = catalog.member(owner.qualname, member)
    return found[0].name if found is not None else None


def _function(code: str) -> ast.FunctionDef | None:
    """The first function in a chunk's code. A method's code starts at its first character
    while its other lines keep their indent: as a test chunk (decorators and ``def`` at the
    class's indent), or as a definition (``def`` alone, then its body one level deeper)."""
    lines = code.splitlines()
    rest = [ln for ln in lines[1:] if ln.strip()]
    tries = []
    if lines and rest:
        following = rest[0]
        indent = following[: len(following) - len(following.lstrip())]
        if not lines[0].startswith((" ", "\t")):
            tries.append(textwrap.dedent("\n".join([indent + lines[0], *lines[1:]])))
        body = textwrap.dedent("\n".join(lines[1:]))
        tries.append(lines[0] + "\n" + textwrap.indent(body, "    "))
    tries.append(textwrap.dedent(code))
    for text in tries:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        found = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)), None)
        if found is not None:
            return found
    return None


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else ""
    return node.id if isinstance(node, ast.Name) else ""


def self_calls(fn: ast.FunctionDef, skip: set[str]) -> tuple[list[str], dict[str, str]]:
    """The function's ``self`` calls in source order (``self.`` dropped), and one example of
    each as written. ``skip``: first steps left out (the assertion objects)."""
    bound: dict[str, str] = {}
    order: list[tuple[int, int, str, str]] = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            value = node.value
            target = value.func if isinstance(value, ast.Call) else value
            if isinstance(target, ast.Attribute):
                name = _dotted(target)
                head, _, rest = name.partition(".")
                if head in bound and rest:
                    name = f"{bound[head]}.{rest}"
                if name.startswith("self."):
                    called = "()" if isinstance(value, ast.Call) else ""
                    bound[node.targets[0].id] = name + called
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        head, _, rest = name.partition(".")
        if head in bound and rest:
            name = f"{bound[head]}.{rest}"
        if not name.startswith("self.") or name.count(".") < 1:
            continue
        short = name.removeprefix("self.")
        if short.split(".")[0] in skip or short.startswith("assert"):
            continue
        text = ast.unparse(node)
        order.append((node.lineno, node.col_offset, short, text[:160]))
    order.sort()
    calls = [short for _, _, short, _ in order]
    examples: dict[str, str] = {}
    for _, _, short, text in order:
        examples.setdefault(short, text)
    return calls, examples


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    text = ast.unparse(fn.args)
    return f"({text})"


def build_usage(index: IndexData, settings: Settings) -> UsageTable:
    v = settings.validation
    skip = {o.removeprefix("self.") for o in [v.assertion_object, *v.extra_assertion_objects]}
    table = UsageTable()
    for chunk in index.chunks:
        if chunk.kind != "test" or chunk.inherited_from:
            continue
        fn = _function(chunk.code)
        if fn is None:
            continue
        calls, examples = self_calls(fn, skip)
        table.sequences[chunk.id] = calls
        table.examples[chunk.id] = examples
        table._tests[chunk.id] = chunk
    for path, record in sorted(index.files.items()):
        if record.info is None or is_test_file(path, settings.index):
            continue
        for fn_info in record.info.functions:
            table.definitions.append(_definition("", fn_info, path, skip))
        for cls in record.info.classes:
            for method in cls.methods:
                table.definitions.append(_definition(cls.name, method, path, skip))
    return table


def _definition(owner: str, info: FunctionInfo, path: str, skip: set[str]) -> Definition:
    fn = _function(info.code)
    calls = tuple(self_calls(fn, skip)[0]) if fn is not None else ()
    signature = _signature(fn) if fn is not None else "(...)"
    doc = (info.docstring or "").strip().splitlines()
    return Definition(
        owner=owner,
        name=info.name,
        signature=signature,
        doc=doc[0][:160] if doc else "",
        file_path=path,
        line=info.start_line,
        calls=calls,
    )


_CACHE: dict[int, tuple[object, UsageTable]] = {}


def usage_table(index: IndexData, settings: Settings) -> UsageTable:
    """The table for this index, built once per index."""
    hit = _CACHE.get(id(index))
    if hit is not None and hit[0] is index.chunks:
        return hit[1]
    table = build_usage(index, settings)
    _CACHE.clear()
    _CACHE[id(index)] = (index.chunks, table)
    return table


def _where(position: float) -> str:
    return (
        "at the start" if position < 0.34 else "at the end" if position > 0.66 else "in the middle"
    )


def render_scope(uses: list[CallUse], limit: int) -> str:
    """A scope's calls as rows a prompt can carry: ``U<n>`` labels, most used first."""
    rows = [
        f"U{n}: `self.{u.call}` used by {u.tests} test(s), usually {_where(u.position)}"
        + (f", defined in {u.defined_in}" if u.defined_in else "")
        + f"; e.g. `{u.example}`"
        for n, u in enumerate(uses[:limit], 1)
    ]
    if len(uses) > limit:
        rows.append(f"... {len(uses) - limit} more call(s) used by fewer tests")
    return "\n".join(rows)
