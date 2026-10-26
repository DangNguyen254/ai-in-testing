"""Insert a proposed member into its class and check the result. Code only.

A proposal may add code, never change it: the patched file must keep every original
top-level statement and every original member of the class exactly as it was (compared as
syntax trees), and differ only by the new member (a method, or a property with an optional
setter) at the end of the class. The new code may use only what exists: members of the class
and its bases, names the module already binds, and builtins; no new imports.
"""

from __future__ import annotations

import ast
import builtins
import textwrap

from ticket2test.index.catalog import SymbolCatalog
from ticket2test.validate.code import bound_names

_BUILTINS = set(dir(builtins))


def insert_member(source: str, class_name: str, member_code: str) -> str:
    """The file with ``member_code`` appended to ``class_name`` in the class's own indent."""
    tree = ast.parse(source)
    target = _class(tree, class_name)
    lines = source.splitlines(keepends=True)
    first = lines[target.body[0].lineno - 1]
    indent = first[: len(first) - len(first.lstrip())]
    body = textwrap.dedent(member_code.strip("\n")).splitlines()
    block = "".join(f"{indent}{line}\n" if line.strip() else "\n" for line in body)
    end = target.end_lineno or target.lineno
    if not lines[end - 1].endswith("\n"):
        lines[end - 1] += "\n"
    return "".join([*lines[:end], "\n", block, *lines[end:]])


def check_patched(
    before: str,
    after: str,
    class_name: str,
    member: str,
    kind: str,
    catalog: SymbolCatalog,
    qualname: str,
) -> list[str]:
    """Findings (empty when the patch only adds the member and uses only what exists)."""
    try:
        old_tree, new_tree = ast.parse(before), ast.parse(after)
    except SyntaxError as exc:
        return [f"the patched file does not parse: {exc.msg} (line {exc.lineno})"]
    findings: list[str] = []
    old_top, new_top = old_tree.body, new_tree.body
    if len(old_top) != len(new_top):
        findings.append("statements were added or removed outside the class (new imports?)")
    for old, new in zip(old_top, new_top, strict=False):
        is_target = isinstance(old, ast.ClassDef) and old.name == class_name
        if not is_target and ast.dump(old) != ast.dump(new):
            findings.append(f"existing code outside {class_name} changed (line {old.lineno})")
    old_cls, new_cls = _class(old_tree, class_name), _class(new_tree, class_name)
    kept = new_cls.body[: len(old_cls.body)]
    changed = [
        getattr(o, "name", f"line {o.lineno}")
        for o, n in zip(old_cls.body, kept, strict=False)
        if ast.dump(o) != ast.dump(n)
    ]
    if changed or len(kept) < len(old_cls.body):
        findings.append(f"existing members of {class_name} changed: {changed or 'removed'}")
    if [ast.dump(d) for d in old_cls.decorator_list] != [
        ast.dump(d) for d in new_cls.decorator_list
    ] or [ast.dump(b) for b in old_cls.bases] != [ast.dump(b) for b in new_cls.bases]:
        findings.append(f"the decorators or bases of {class_name} changed")
    added = new_cls.body[len(old_cls.body) :]
    defs = [n for n in added if isinstance(n, ast.FunctionDef)]
    if len(defs) != len(added) or not defs:
        findings.append("add exactly one member: a method, or a property (and its setter)")
        return findings
    if any(d.name != member for d in defs):
        findings.append(f"the new member must be named {member!r}, as the test uses it")
    if member in {getattr(n, "name", None) for n in old_cls.body}:
        findings.append(f"{class_name} already has {member!r}")
    is_property = any(_dotted(dec).endswith("property") for dec in defs[0].decorator_list)
    if kind == "property" and not is_property:
        findings.append(f"the test reads {member} as a value: make it a property")
    if kind == "method" and is_property:
        findings.append(f"the test calls {member}(): make it a method")
    if len(defs) > 2 or (len(defs) == 2 and not is_property):
        findings.append("only a property may have a second definition (its setter)")
    findings += _unknown_names(defs, new_tree, catalog, qualname, member)
    return findings


def _unknown_names(
    defs: list[ast.FunctionDef],
    module: ast.Module,
    catalog: SymbolCatalog,
    qualname: str,
    member: str,
) -> list[str]:
    known_members = set(catalog.members_of(qualname)) | {member}
    bound = bound_names(module) | _BUILTINS
    unknown: set[str] = set()
    for fn in defs:
        local = {a.arg for a in [*fn.args.args, *fn.args.kwonlyargs, *fn.args.posonlyargs]}
        local |= {
            n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        }
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr not in known_members
            ):
                unknown.add(f"self.{node.attr}")
            elif (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id not in local | bound
            ):
                unknown.add(node.id)
    return [f"uses names that don't exist: {', '.join(sorted(unknown))}"] if unknown else []


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise ValueError(f"class {name} not found")


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return node.id if isinstance(node, ast.Name) else ""
