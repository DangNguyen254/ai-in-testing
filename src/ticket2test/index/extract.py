"""tree-sitter extraction of the structure of one Python file.

Only module-level functions and classes, plus methods directly inside those classes, are
extracted. Code is always a whole definition (decorators included), never cut mid-function.
"""

from __future__ import annotations

import hashlib
import re
from functools import cache

import tree_sitter_python
from pydantic import BaseModel, ConfigDict, Field
from tree_sitter import Language, Node, Parser

from ticket2test.models.chunk import Refs


class ParseError(ValueError):
    """The file has syntax errors; it is skipped rather than half-indexed."""


class Param(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    annotation: str | None = None


class Assign(BaseModel):
    """``name: annotation = value`` in a class body, or ``self.name = value`` in a method."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    annotation: str | None = None
    call: str | None = None  # callee when the value is a call, e.g. "ApiClient"
    line: int


class FunctionInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    start_line: int
    end_line: int
    decorators: list[str] = Field(default_factory=list)  # source text without "@"
    params: list[Param] = Field(default_factory=list)
    returns: str | None = None
    # Callees of ``return Callee(...)``, and ``self`` chains of ``return self.a.b`` (a helper
    # that hands back a page object), in order.
    returned_calls: list[str] = Field(default_factory=list)
    docstring: str | None = None
    code: str
    self_assignments: list[Assign] = Field(default_factory=list)
    refs: Refs = Field(default_factory=Refs)
    # Import statements inside the function (``from pages.x import Page`` in a property): they
    # decide which class a name means there, before the module's own imports.
    local_imports: list[str] = Field(default_factory=list)


class ClassInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    start_line: int
    end_line: int
    decorators: list[str] = Field(default_factory=list)
    bases: list[str] = Field(default_factory=list)
    docstring: str | None = None
    code: str  # the whole class
    header_code: str  # class line, docstring, and class-level statements (no methods)
    attributes: list[Assign] = Field(default_factory=list)
    methods: list[FunctionInfo] = Field(default_factory=list)
    refs: Refs = Field(default_factory=Refs)  # the whole class
    header_refs: Refs = Field(default_factory=Refs)  # bases + class-level statements only


class FileInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    module: str
    sha256: str
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    assignments: list[Assign] = Field(default_factory=list)  # module-level
    imports: list[str] = Field(default_factory=list)  # top-level import statements, as written


@cache
def _parser() -> Parser:
    return Parser(Language(tree_sitter_python.language()))


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def module_name(path: str, roots: list[str] | tuple[str, ...] = ()) -> str:
    """The module name a file is imported by: its path from the deepest import root holding
    it (``index.import_roots``: folders the suite puts on the import path), else from the
    repo root."""
    clean = [r.strip("/") for r in roots if r.strip("/")]
    root = max((r for r in clean if path.startswith(r + "/")), key=len, default="")
    parts = path[len(root) + 1 if root else 0 :].removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or "__init__"


def extract_file(path: str, source: bytes, roots: list[str] | tuple[str, ...] = ()) -> FileInfo:
    tree = _parser().parse(source)
    root = tree.root_node
    if root.has_error:
        line = _first_error_line(root)
        raise ParseError(f"{path}: syntax error near line {line}")

    functions: list[FunctionInfo] = []
    classes: list[ClassInfo] = []
    assignments: list[Assign] = []
    imports: list[str] = []
    for node in root.named_children:
        if node.type in ("import_statement", "import_from_statement"):
            imports.append(_text(node))
            continue
        definition, decorators = _unwrap(node)
        if definition.type == "function_definition":
            functions.append(_function(definition, node, decorators))
        elif definition.type == "class_definition":
            classes.append(_class(definition, node, decorators))
        elif node.type == "expression_statement":
            assignments.extend(_assignments_in(node))
    return FileInfo(
        path=path,
        module=module_name(path, roots),
        sha256=sha256_of(source),
        functions=functions,
        classes=classes,
        assignments=assignments,
        imports=imports,
    )


# --- helpers -------------------------------------------------------------------------------


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8")


def _first_error_line(node: Node) -> int:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == "ERROR" or current.is_missing:
            return current.start_point[0] + 1
        stack.extend(reversed(current.children))
    return node.start_point[0] + 1


def _unwrap(node: Node) -> tuple[Node, list[str]]:
    """Return the definition inside a decorated_definition and its decorators (no '@')."""
    if node.type != "decorated_definition":
        return node, []
    decorators = [
        _text(d).lstrip("@").strip() for d in node.named_children if d.type == "decorator"
    ]
    definition = node.child_by_field_name("definition")
    return (definition if definition is not None else node), decorators


def _docstring(body: Node | None) -> str | None:
    if body is None or not body.named_children:
        return None
    first = body.named_children[0]
    if first.type == "expression_statement" and first.named_children:
        string = first.named_children[0]
        if string.type == "string":
            raw = _text(string)
            return re.sub(r'^[rRuUbBfF]*("""|\'\'\'|"|\')|("""|\'\'\'|"|\')$', "", raw).strip()
    return None


def _params(node: Node | None) -> list[Param]:
    params: list[Param] = []
    if node is None:
        return params
    for child in node.named_children:
        if child.type == "identifier":
            params.append(Param(name=_text(child)))
        elif child.type in ("typed_parameter", "typed_default_parameter", "default_parameter"):
            name_node = child.child_by_field_name("name")
            if name_node is None:  # typed_parameter has no "name" field; first child is the name
                name_node = next((c for c in child.named_children if c.type == "identifier"), None)
            type_node = child.child_by_field_name("type")
            params.append(Param(name=_text(name_node), annotation=_text(type_node) or None))
    return params


_DECLARING_PARENTS = frozenset(
    {"parameters", "lambda_parameters", "list_splat_pattern", "dictionary_splat_pattern"}
)
_NAMED_PARAMETERS = frozenset({"default_parameter", "typed_default_parameter", "typed_parameter"})


def _is_reference(node: Node) -> bool:
    """An identifier that refers to something (not a declaration or a keyword name)."""
    parent = node.parent
    if parent is None:
        return True
    if parent.type in _DECLARING_PARENTS:
        return False
    if parent.type in _NAMED_PARAMETERS:
        # The declared name is the first identifier child; the type/default are references.
        first = next((c for c in parent.named_children if c.type == "identifier"), None)
        return first is None or first.start_byte != node.start_byte
    if parent.type == "keyword_argument":
        name = parent.child_by_field_name("name")
        return name is None or name.start_byte != node.start_byte
    if parent.type in ("function_definition", "class_definition"):
        name = parent.child_by_field_name("name")
        return name is None or name.start_byte != node.start_byte
    return True


def _call_name(call: Node) -> str | None:
    function = call.child_by_field_name("function")
    if function is None:
        return None
    if function.type == "identifier":
        return _text(function)
    if function.type == "attribute":
        return _text(function.child_by_field_name("attribute")) or None
    return None


def _self_chain(node: Node) -> list[str] | None:
    """Steps from ``self`` for an attribute/call expression, or None if not rooted at self.

    A call without arguments stays in the chain as "name()"; a call with arguments ends it.
    """
    if node.type == "identifier":
        return [] if _text(node) == "self" else None
    if node.type == "attribute":
        obj = node.child_by_field_name("object")
        base = _self_chain(obj) if obj is not None else None
        if base is None:
            return None
        return [*base, _text(node.child_by_field_name("attribute"))]
    if node.type == "call":
        arguments = node.child_by_field_name("arguments")
        function = node.child_by_field_name("function")
        if arguments is None or arguments.named_children or function is None:
            return None
        base = _self_chain(function)
        if not base:
            return None
        return [*base[:-1], f"{base[-1]}()"]
    return None


def _refs(nodes: list[Node]) -> Refs:
    calls: dict[str, None] = {}
    names: dict[str, int] = {}
    chains: list[list[str]] = []
    stack = list(reversed(nodes))
    while stack:
        node = stack.pop()
        kind = node.type
        if kind == "comment":
            continue
        if kind == "string":
            # Only f-string interpolations contain code.
            stack.extend(reversed([c for c in node.named_children if c.type == "interpolation"]))
            continue
        if kind == "call":
            name = _call_name(node)
            if name:
                calls.setdefault(name, None)
        elif kind == "identifier" and _is_reference(node):
            text = _text(node)
            if text not in ("self", "cls"):
                names[text] = names.get(text, 0) + 1
        elif kind == "attribute":
            steps = _self_chain(node)
            if steps and len(steps) >= 2:
                chains.append(steps)
        stack.extend(reversed(node.children))
    return Refs(calls=list(calls), names=names, self_chains=_maximal(chains))


def _maximal(chains: list[list[str]]) -> list[list[str]]:
    """Drop chains that are a prefix of a longer one (``a.b`` inside ``a.b.c()``)."""

    def plain(steps: list[str]) -> list[str]:
        return [s.removesuffix("()") for s in steps]

    result: list[list[str]] = []
    for steps in chains:
        p = plain(steps)
        if any(len(o) > len(p) and plain(o)[: len(p)] == p for o in chains):
            continue
        if steps not in result:
            result.append(steps)
    return result


def _self_assignments(body: Node | None) -> list[Assign]:
    """``self.name [: annotation] = value`` anywhere in a function body."""
    found: list[Assign] = []
    stack = [body] if body is not None else []
    while stack:
        node = stack.pop()
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            obj = left.child_by_field_name("object") if left is not None else None
            if (
                left is not None
                and left.type == "attribute"
                and obj is not None
                and _text(obj) == "self"
            ):
                right = node.child_by_field_name("right")
                call = None
                if right is not None and right.type == "call":
                    call = _text(right.child_by_field_name("function")) or None
                found.append(
                    Assign(
                        name=_text(left.child_by_field_name("attribute")),
                        annotation=_text(node.child_by_field_name("type")) or None,
                        call=call,
                        line=node.start_point[0] + 1,
                    )
                )
        if node.type not in ("string", "comment"):
            stack.extend(reversed(node.children))
    found.sort(key=lambda a: a.line)
    return found


def _returned_calls(body: Node | None) -> list[str]:
    """Callees of ``return Callee(...)`` in this function (not in nested defs), in order.

    Unannotated code (``return ItemsPage(*self._args)``) gets its types from these.
    """
    found: list[str] = []
    stack = [body] if body is not None else []
    while stack:
        node = stack.pop()
        if node.type == "return_statement":
            value = next((c for c in node.named_children), None)
            if value is not None and value.type == "call":
                callee = _text(value.child_by_field_name("function"))
                if callee and callee not in found:
                    found.append(callee)
            elif value is not None and value.type == "attribute":
                chain = _text(value)
                if chain.startswith("self.") and chain not in found:
                    found.append(chain)
            continue
        if node.type in ("function_definition", "class_definition", "lambda", "string"):
            continue
        stack.extend(reversed(node.children))
    return found


def _function(definition: Node, outer: Node, decorators: list[str]) -> FunctionInfo:
    body = definition.child_by_field_name("body")
    return FunctionInfo(
        name=_text(definition.child_by_field_name("name")),
        start_line=outer.start_point[0] + 1,
        end_line=outer.end_point[0] + 1,
        decorators=decorators,
        params=_params(definition.child_by_field_name("parameters")),
        returns=_text(definition.child_by_field_name("return_type")) or None,
        returned_calls=_returned_calls(body),
        docstring=_docstring(body),
        code=_text(outer),
        self_assignments=_self_assignments(body),
        refs=_refs(_reference_roots(outer, body)),
        local_imports=_local_imports(body),
    )


def _local_imports(body: Node | None) -> list[str]:
    """Import statements in this function's body (not in nested defs), as written."""
    found: list[str] = []
    stack = [body] if body is not None else []
    while stack:
        node = stack.pop()
        if node.type in ("import_statement", "import_from_statement"):
            found.append(_text(node))
            continue
        if node.type in ("function_definition", "class_definition", "lambda", "string"):
            continue
        stack.extend(reversed(node.children))
    return found


def _reference_roots(outer: Node, body: Node | None) -> list[Node]:
    """Decorators, parameter defaults/annotations, return type, and body (minus docstring)."""
    roots = [c for c in outer.named_children if c.type == "decorator"]
    definition = (
        outer.child_by_field_name("definition") if outer.type == "decorated_definition" else outer
    )
    if definition is not None:
        for field in ("parameters", "return_type", "superclasses"):
            child = definition.child_by_field_name(field)
            if child is not None:
                roots.append(child)
    if body is not None:
        children = list(body.named_children)
        if children and _is_docstring(children[0]):
            children = children[1:]
        roots.extend(children)
    return roots


def _assignments_in(statement: Node) -> list[Assign]:
    found: list[Assign] = []
    for child in statement.named_children:
        if child.type != "assignment":
            continue
        left = child.child_by_field_name("left")
        if left is None or left.type != "identifier":
            continue
        right = child.child_by_field_name("right")
        call = None
        if right is not None and right.type == "call":
            call = _text(right.child_by_field_name("function")) or None
        found.append(
            Assign(
                name=_text(left),
                annotation=_text(child.child_by_field_name("type")) or None,
                call=call,
                line=child.start_point[0] + 1,
            )
        )
    return found


def _class(definition: Node, outer: Node, decorators: list[str]) -> ClassInfo:
    body = definition.child_by_field_name("body")
    superclasses = definition.child_by_field_name("superclasses")
    bases = [
        _text(arg)
        for arg in (superclasses.named_children if superclasses is not None else [])
        if arg.type in ("identifier", "attribute", "subscript")
    ]

    methods: list[FunctionInfo] = []
    attributes: list[Assign] = []
    header_lines: list[str] = []
    class_start = outer.start_point[0]
    body_start = body.start_point[0] if body is not None else definition.end_point[0]
    source_lines = _text(outer).split("\n")
    # Class line(s) up to the body.
    header_lines.extend(source_lines[: max(body_start - class_start, 1)])
    header_nodes: list[Node] = [d for d in outer.named_children if d.type == "decorator"]
    if superclasses is not None:
        header_nodes.append(superclasses)
    for child in body.named_children if body is not None else []:
        inner, inner_decorators = _unwrap(child)
        if inner.type == "function_definition":
            methods.append(_function(inner, child, inner_decorators))
            continue
        header_nodes.append(child)
        if child.type == "expression_statement":
            attributes.extend(_assignments_in(child))
        first = child.start_point[0] - class_start
        last = child.end_point[0] - class_start
        header_lines.extend(source_lines[first : last + 1])

    return ClassInfo(
        name=_text(definition.child_by_field_name("name")),
        start_line=class_start + 1,
        end_line=outer.end_point[0] + 1,
        decorators=decorators,
        bases=bases,
        docstring=_docstring(body),
        code=_text(outer),
        header_code="\n".join(header_lines),
        attributes=attributes,
        methods=methods,
        refs=_refs(_reference_roots(outer, body)),
        header_refs=_refs([n for n in header_nodes if not _is_docstring(n)]),
    )


def _is_docstring(node: Node) -> bool:
    return (
        node.type == "expression_statement"
        and bool(node.named_children)
        and node.named_children[0].type == "string"
    )
