"""The local style of an existing file, and edits that leave its existing lines untouched.

Suites drift: some files use another indent width or quote style than the configured one, and
data files differ in key spacing. Purely cosmetic rules follow the file being patched
(``style.follow_local``): new code takes that file's indent and quotes, and new data entries
are inserted as text in the file's own JSON style, so no existing line changes.
"""

from __future__ import annotations

import io
import json
import re
import tokenize
from collections import Counter
from itertools import pairwise
from typing import Any

from ticket2test.config import JsonStyle, PythonStyle

_BLOCK_OPENER = re.compile(r":\s*(#.*)?$")


def detect_python_style(source: str, base: PythonStyle) -> PythonStyle:
    """``base`` with the file's own indent width and quote style, where the file shows one."""
    lines = source.splitlines()
    steps: Counter[int] = Counter()
    for line, following in pairwise(lines):
        if not _BLOCK_OPENER.search(line) or not following.strip():
            continue
        step = _width(following) - _width(line)
        if 0 < step <= 8:
            steps[step] += 1
    quotes: Counter[str] = Counter()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.STRING:
                body = token.string.lstrip("rRbBuUfF")
                if body[:3] in ('"""', "'''"):
                    continue  # docstrings and long strings say little about quote style
                if body[:1] in ('"', "'") and "'" not in body[1:-1] and '"' not in body[1:-1]:
                    quotes["double" if body[0] == '"' else "single"] += 1
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    update: dict[str, Any] = {}
    if steps:
        update["indent_width"] = steps.most_common(1)[0][0]
    if quotes:
        update["quote_style"] = quotes.most_common(1)[0][0]
    return base.model_copy(update=update)


def detect_json_style(text: str, base: JsonStyle) -> JsonStyle:
    """``base`` with the file's own indent and key separator, where the file shows them."""
    update: dict[str, Any] = {}
    indents = [_width(line) for line in text.splitlines()[1:] if line.strip()]
    positive = [i for i in indents if i > 0]
    if positive:
        update["indent"] = min(positive)
    key = re.search(r'"(?:[^"\\]|\\.)*"(\s*):(\s*)\S', text)
    if key is not None:
        update["key_separator"] = ":" + key.group(2)[:1].replace("\n", "")
    update["final_newline"] = text.endswith("\n")
    return base.model_copy(update=update)


def insert_entries(
    text: str, new: list[dict[str, Any]], after: int | None, style: JsonStyle
) -> str | None:
    """``text`` (a top-level JSON array) with ``new`` inserted after its element number
    ``after`` (None: at the end), formatted in ``style``; every existing line is kept as is.
    None when the text isn't an array this can edit (then the caller re-serializes)."""
    spans = _array_spans(text)
    if spans is None or not new:
        return None
    unit = " " * style.indent
    blocks = [
        "\n".join(
            unit + line
            for line in json.dumps(
                entry,
                indent=style.indent,
                separators=(style.item_separator, style.key_separator),
                ensure_ascii=style.ensure_ascii,
            ).splitlines()
        )
        for entry in new
    ]
    joined = (style.item_separator + "\n").join(blocks)
    if not spans:  # an empty array
        close = text.rindex("]")
        return text[:close].rstrip() + "\n" + joined + "\n" + text[close:]
    at = len(spans) - 1 if after is None else max(0, min(after, len(spans) - 1))
    end = spans[at][1]
    return text[:end] + style.item_separator + "\n" + joined + text[end:]


def _array_spans(text: str) -> list[tuple[int, int]] | None:
    """(start, end) of each element of a top-level JSON array of objects, or None if the
    text isn't one."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        return None
    spans: list[tuple[int, int]] = []
    depth, start, in_string, escape = 0, -1, False, False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            if depth == 1 and ch == "{":
                start = i
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 1 and ch == "}":
                spans.append((start, i + 1))
            elif depth == 0:
                break
    return spans if len(spans) == len(data) else None


def _width(line: str) -> int:
    return len(line) - len(line.lstrip(" "))
