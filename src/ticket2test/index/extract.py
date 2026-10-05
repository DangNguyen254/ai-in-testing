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
    docstring: str | None = None
    code: str
    self_assignments: list[Assign] = Field(default_factory=list)


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


class FileInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    module: str
    sha256: str
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    assignments: list[Assign] = Field(default_factory=list)  # module-level


@cache
def _parser() -> Parser:
    return Parser(Language(tree_sitter_python.language()))


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def module_name(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or "__init__"


def extract_file(path: str, source: bytes) -> FileInfo:
    tree = _parser().parse(source)
    root = tree.root_node
    if root.has_error:
        line = _first_error_line(root)
        raise ParseError(f"{path}: syntax error near line {line}")

    functions: list[FunctionInfo] = []
    classes: list[ClassInfo] = []
    assignments: list[Assign] = []
    for node in root.named_children:
        definition, decorators = _unwrap(node)
        if definition.type == "function_definition":
            functions.append(_function(definition, node, decorators))
        elif definition.type == "class_definition":
            classes.append(_class(definition, node, decorators))
        elif node.type == "expression_statement":
            assignments.extend(_assignments_in(node))
    return FileInfo(
        path=path,
        module=module_name(path),
        sha256=sha256_of(source),
        functions=functions,
        classes=classes,
        assignments=assignments,
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


# self.name [: annotation] = [Callee(]  -- not "other.self.x", not "self.x == y"
_SELF_ASSIGN = re.compile(
    r"(?<![\w.])self\.(?P<name>\w+)\s*(?::\s*(?P<ann>[^=\n]+?))?\s*=(?!=)\s*"
    r"(?:(?P<call>[A-Za-z_][\w.]*)\s*\()?"
)


def _function(definition: Node, outer: Node, decorators: list[str]) -> FunctionInfo:
    body = definition.child_by_field_name("body")
    body_text = _text(body)
    body_line = (body.start_point[0] + 1) if body is not None else outer.start_point[0] + 1
    self_assignments = [
        Assign(
            name=match.group("name"),
            annotation=(match.group("ann") or "").strip() or None,
            call=match.group("call"),
            line=body_line + body_text.count("\n", 0, match.start()),
        )
        for match in _SELF_ASSIGN.finditer(body_text)
    ]
    return FunctionInfo(
        name=_text(definition.child_by_field_name("name")),
        start_line=outer.start_point[0] + 1,
        end_line=outer.end_point[0] + 1,
        decorators=decorators,
        params=_params(definition.child_by_field_name("parameters")),
        returns=_text(definition.child_by_field_name("return_type")) or None,
        docstring=_docstring(body),
        code=_text(outer),
        self_assignments=self_assignments,
    )


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
    for child in body.named_children if body is not None else []:
        inner, inner_decorators = _unwrap(child)
        if inner.type == "function_definition":
            methods.append(_function(inner, child, inner_decorators))
            continue
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
    )
