"""Rule-based extraction of steps to reproduce / expected / actual from Markdown.

A section starts at a heading whose text matches a known keyword:
- Markdown headings: ``### To reproduce``
- bold-only lines: ``**Expected behavior**``
- label lines: ``Actual: it crashes`` / ``**Steps to reproduce:**`` (content may follow)

Any other Markdown heading ends the current section. Headings inside code blocks are ignored.
Nothing is inferred: if no section is found, the field stays empty.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from typing import Literal

from ticket2test.normalize.markdown import (
    Line,
    collapse_blank_lines,
    lines_to_text,
    prose_line_to_text,
)

Kind = Literal["steps", "expected", "actual"]

_KIND_PATTERNS: dict[Kind, re.Pattern[str]] = {
    "steps": re.compile(
        r"^(steps( to (reproduce|repro))?|to reproduce|how to reproduce|reproduce|"
        r"reproduction( steps)?|repro( steps)?|code to reproduce|mcve|mre|"
        r"(minimal|reproducible|minimal reproducible)( code)? example)\b"
    ),
    "expected": re.compile(r"^expected\b"),
    "actual": re.compile(
        r"^(actual\b|(current|observed) (behaviou?r|results?|outcome|output)\b|"
        r"what (actually )?happen)"
    ),
}

_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BOLD_LINE = re.compile(r"^\s*\*\*(.+?)\*\*\s*:?\s*$")
_LABEL_LINE = re.compile(r"^\s*(?:\*\*)?([A-Za-z][A-Za-z ]{0,40}?)\s*(?::\*\*|\*\*:|:)\s*(.*)$")
_LIST_ITEM = re.compile(r"^(\s*)(?:\d+[.)]|[-*+])\s+(.*)$")
_MAX_HEADING_WORDS = 8


@dataclass
class Sections:
    steps: list[str] = field(default_factory=list)
    expected: str | None = None
    actual: str | None = None


def heading_kind(text: str) -> Kind | None:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    normalized = " ".join(normalized.split())
    if not normalized or len(normalized.split()) > _MAX_HEADING_WORDS:
        return None
    for kind, pattern in _KIND_PATTERNS.items():
        if pattern.match(normalized):
            return kind
    return None


def extract_sections(lines: list[Line]) -> Sections:
    buckets: dict[Kind, list[list[Line]]] = {"steps": [], "expected": [], "actual": []}
    current: list[Line] | None = None

    for line in lines:
        if line.in_code:
            if current is not None:
                current.append(line)
            continue

        md_heading = _MD_HEADING.match(line.text)
        if md_heading:
            kind = heading_kind(md_heading.group(1))
            current = _open(buckets, kind) if kind else None  # other headings end a section
            continue

        bold = _BOLD_LINE.match(line.text)
        if bold and (kind := heading_kind(bold.group(1))):
            current = _open(buckets, kind)
            continue

        label = _LABEL_LINE.match(line.text)
        if label and (kind := heading_kind(label.group(1))):
            current = _open(buckets, kind)
            if label.group(2).strip():
                current.append(Line(label.group(2), False))
            continue

        if current is not None:
            current.append(line)

    return Sections(
        steps=[step for section in buckets["steps"] for step in split_steps(section)],
        expected=_join_text(buckets["expected"]),
        actual=_join_text(buckets["actual"]),
    )


def _open(buckets: dict[Kind, list[list[Line]]], kind: Kind) -> list[Line]:
    section: list[Line] = []
    buckets[kind].append(section)
    return section


def _join_text(sections: list[list[Line]]) -> str | None:
    text = collapse_blank_lines("\n\n".join(lines_to_text(s) for s in sections))
    return text or None


def split_steps(lines: list[Line]) -> list[str]:
    """Split a section into steps: list items, paragraphs, and code blocks (verbatim)."""
    steps: list[list[str]] = []
    current: list[str] | None = None
    in_list_item = False
    prev_blank = True
    i = 0
    while i < len(lines):
        if lines[i].in_code:
            block: list[str] = []
            while i < len(lines) and lines[i].in_code:
                block.append(lines[i].text)
                i += 1
            if in_list_item and current is not None and block[0][:1].isspace():
                # A code block indented under a list item belongs to that item.
                current.extend(textwrap.dedent("\n".join(block)).split("\n"))
            else:
                steps.append(block)
                current = None
                in_list_item = False
            prev_blank = False
            continue

        text = lines[i].text
        i += 1
        if not text.strip():
            prev_blank = True
            if not in_list_item:
                current = None
            continue

        item = _LIST_ITEM.match(text)
        if item:
            current = [prose_line_to_text(item.group(2))]
            steps.append(current)
            in_list_item = True
        elif current is not None and (not prev_blank or (in_list_item and text[:1].isspace())):
            current.append(prose_line_to_text(text.strip()))
        else:
            current = [prose_line_to_text(text)]
            steps.append(current)
            in_list_item = False
        prev_blank = False

    return [s for s in (collapse_blank_lines("\n".join(step)) for step in steps) if s]
