"""Python code in the suite's style: optional annotation stripping, then ruff (imports, format).

Ruff runs with ``--isolated`` and the configured values only, so the result depends on the
config, never on config files that happen to sit near the output. Ruff parses the code; it
never imports or runs it (Hard Constraint 3 is about execution).
"""

from __future__ import annotations

import ast
import subprocess

import tree_sitter_python
from ruff.__main__ import find_ruff_bin
from tree_sitter import Language, Node, Parser

from ticket2test.config import PythonStyle

_PARSER = Parser(Language(tree_sitter_python.language()))
_TIMEOUT_SECONDS = 60


class FormatError(RuntimeError):
    """Ruff could not format the code (usually a syntax error)."""


def target_syntax_error(code: str, target: str | None) -> str | None:
    """Why ``code`` doesn't parse with Python ``target``'s grammar ("3.8"), or None. Best effort:
    Python's parser rejects most newer syntax for an older ``feature_version``, not all."""
    if not target:
        return None
    major, minor = (int(part) for part in target.split("."))
    try:
        ast.parse(code, feature_version=(major, minor))
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    return None


def format_python(code: str, style: PythonStyle, first_party: list[str]) -> str:
    """Strip annotations (if configured), sort imports, drop unused imports, then format."""
    if style.strip_annotations:
        code = strip_annotations(code)
    options = [
        f"indent-width = {style.indent_width}",
        f"line-length = {style.line_length}",
        f'format.line-ending = "{style.line_ending}"',
        f'format.quote-style = "{style.quote_style}"',
        f"lint.isort.known-first-party = {_toml_list(first_party)}",
        *_target_option(style),
    ]
    fixed = _ruff(["check", "--select", "I,F401", "--fix", "--exit-zero"], options, code)
    formatted = _ruff(["format"], options, fixed)
    if not style.final_newline:
        formatted = formatted.rstrip("\n")
    return formatted


def sort_imports(code: str, style: PythonStyle, first_party: list[str]) -> str:
    """Only the import block sorted and merged (statements from the same module combined);
    every other line stays as it is."""
    options = [
        f"indent-width = {style.indent_width}",
        f"line-length = {style.line_length}",
        f"lint.isort.known-first-party = {_toml_list(first_party)}",
        *_target_option(style),
    ]
    return _ruff(["check", "--select", "I", "--fix", "--exit-zero"], options, code)


def _target_option(style: PythonStyle) -> list[str]:
    """Ruff's ``target-version`` (e.g. "py38"), so formatting never needs newer syntax."""
    if not style.target_version:
        return []
    return [f'target-version = "py{style.target_version.replace(".", "")}"']


def _ruff(command: list[str], options: list[str], code: str) -> str:
    args = [find_ruff_bin(), *command, "--isolated", "--no-cache"]
    for option in options:
        args += ["--config", option]
    result = subprocess.run(
        [*args, "--stdin-filename", "generated.py", "-"],
        input=code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise FormatError(f"ruff {command[0]} failed: {detail[0] if detail else 'no output'}")
    return result.stdout


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(f'"{v}"' for v in values) + "]"


# --- annotations ----------------------------------------------------------------------------


def strip_annotations(code: str) -> str:
    """Remove parameter, return, and variable annotations; keep comments and layout.

    ``x: T = v`` becomes ``x = v``; a bare ``x: T`` line is dropped; the
    ``from __future__ import annotations`` line is dropped. Unused typing imports are left for
    ruff to remove.
    """
    source = code.encode("utf-8")
    tree = _PARSER.parse(source)
    if tree.root_node.has_error:
        return code  # leave broken code alone; validation reports it
    edits = sorted(_edits(tree.root_node, source), key=lambda e: e[0], reverse=True)
    out = source
    for start, end, text in edits:
        out = out[:start] + text + out[end:]
    return out.decode("utf-8")


def _edits(root: Node, source: bytes) -> list[tuple[int, int, bytes]]:
    edits: list[tuple[int, int, bytes]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        kind = node.type
        if kind == "function_definition":
            returns = node.child_by_field_name("return_type")
            params = node.child_by_field_name("parameters")
            if returns is not None and params is not None:
                edits.append((params.end_byte, returns.end_byte, b""))
        elif kind == "typed_parameter":
            first = node.children[0]  # the name, or *args / **kwargs
            edits.append(
                (node.start_byte, node.end_byte, source[first.start_byte : first.end_byte])
            )
            continue
        elif kind == "typed_default_parameter":
            name = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if name is not None and value is not None:
                edits.append((name.end_byte, value.start_byte, b"="))
        elif kind == "assignment" and node.child_by_field_name("type") is not None:
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is not None and right is not None:
                edits.append((left.end_byte, right.start_byte, b" = "))
            elif node.parent is not None:
                edits.append(_whole_lines(node.parent, source))
            continue
        elif (
            kind == "future_import_statement"
            and b"annotations" in source[node.start_byte : node.end_byte]
        ):
            edits.append(_whole_lines(node, source))
            continue
        stack.extend(node.children)
    return edits


def _whole_lines(node: Node, source: bytes) -> tuple[int, int, bytes]:
    start = source.rfind(b"\n", 0, node.start_byte) + 1
    end = source.find(b"\n", node.end_byte)
    return start, len(source) if end == -1 else end + 1, b""
