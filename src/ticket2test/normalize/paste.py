"""A pasted ticket file (adapters/tickets/paste.py) -> Ticket.

The ``##`` sections fill the matching fields. Steps, expected and actual come from their own
sections first; when those are empty, from the same kind of sections inside the description,
then inside the pasted test plan (it is often where the full steps live). The test plan and
readable attachments are also kept in the description, under their own labels, so the draft
step sees them. A pasted ticket is a tracker ticket copied by hand: its source is ``jira``.
"""

from __future__ import annotations

import re
from typing import Any

from ticket2test.adapters.tickets.base import RawTicket
from ticket2test.config import Settings
from ticket2test.models.ticket import Comment, SourceInfo, Ticket
from ticket2test.normalize.markdown import extract_urls, lines_to_text, split_lines
from ticket2test.normalize.sections import Sections, extract_sections, split_steps

_TITLE = re.compile(r"^#\s+(?P<key>[^\s:]+)\s*[:\-\u2013]\s*(?P<title>.+?)\s*$")
_SECTION = re.compile(r"^##\s+(?P<name>.+?)\s*$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ALIASES = {
    "components": "components",
    "component": "components",
    "labels": "labels",
    "label": "labels",
    "description": "description",
    "summary": "description",
    "steps to reproduce": "steps",
    "steps": "steps",
    "repro steps": "steps",
    "reproduction steps": "steps",
    "expected": "expected",
    "expected result": "expected",
    "expected results": "expected",
    "expected behavior": "expected",
    "expected behaviour": "expected",
    "actual": "actual",
    "actual result": "actual",
    "actual results": "actual",
    "actual behavior": "actual",
    "actual behaviour": "actual",
    "test plan": "test_plan",
    "attachments": "attachments",
    "attachment": "attachments",
    "comments": "comments",
    "links": "links",
}


class PasteError(ValueError):
    """The pasted file can't be read as a ticket (e.g. no title line)."""


def normalize_paste(raw: RawTicket, settings: Settings) -> Ticket:
    text = _COMMENT.sub("", str(raw.payload.get("text") or ""))
    key, title, sections, extra = _split(text, raw.ref)

    def lines(name: str) -> list[Any]:
        return split_lines(sections.get(name, ""))

    found = Sections(
        split_steps(lines("steps")),
        lines_to_text(lines("expected")) or None,
        lines_to_text(lines("actual")) or None,
    )
    for fallback in ("description", "test_plan"):  # sections written inside other text
        inner = extract_sections(lines(fallback))
        found.steps = found.steps or inner.steps
        found.expected = found.expected or inner.expected
        found.actual = found.actual or inner.actual

    description = _description(sections, extra, raw.payload.get("attachments") or [])
    every = split_lines(text)
    links = dict.fromkeys([*(_items(sections.get("links", ""))), *extract_urls(every)])
    max_chars = settings.normalize.max_comment_chars
    comments = [
        Comment(body=body[:max_chars])
        for body in (c.strip() for c in re.split(r"(?m)^\s*---\s*$", sections.get("comments", "")))
        if body
    ]
    kept = comments[: settings.normalize.max_comments]
    return Ticket(
        id=key,
        title=title,
        description=description,
        steps_to_reproduce=found.steps,
        expected=found.expected,
        actual=found.actual,
        components=_items(sections.get("components", "")),
        labels=_items(sections.get("labels", "")),
        comments=kept,
        comments_omitted=len(comments) - len(kept),
        links=[u for u in links if u.startswith(("http://", "https://"))],
        source=SourceInfo(system="jira", ref=key),
    )


def _split(text: str, ref: str) -> tuple[str, str, dict[str, str], list[tuple[str, str]]]:
    """(key, title, known sections by field, unknown sections as (heading, body))."""
    key, title = ref, ""
    sections: dict[str, list[str]] = {}
    extra: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        heading = _TITLE.match(line)
        if heading and not title:
            key, title = heading["key"], heading["title"]
            current = None
            continue
        section = _SECTION.match(line)
        if section:
            name = section["name"].strip().rstrip(":").lower()
            field = _ALIASES.get(name)
            if field is None:
                extra.append((section["name"].strip(), []))
                current = extra[-1][1]
            else:
                current = sections.setdefault(field, [])
            continue
        if current is not None:
            current.append(line)
    if not title or title.startswith("<"):
        raise PasteError(f"{ref}: the first line must be '# <KEY>: <title>'")
    joined = {k: "\n".join(v).strip() for k, v in sections.items()}
    return key, title, joined, [(h, "\n".join(b).strip()) for h, b in extra]


def _description(
    sections: dict[str, str], extra: list[tuple[str, str]], attachments: list[dict[str, Any]]
) -> str | None:
    parts = [sections.get("description", "")]
    parts += [f"{heading}:\n{body}" for heading, body in extra if body]
    if sections.get("test_plan"):
        parts.append(f"Test plan (pasted):\n{sections['test_plan']}")
    for item in attachments:
        name, body = item.get("name"), item.get("text")
        parts.append(
            f"Attachment {name}:\n{body.strip()}" if body else f"[attachment not read: {name}]"
        )
    text = "\n\n".join(p for p in parts if p and p.strip())
    return lines_to_text(split_lines(text)) or None


def _items(text: str) -> list[str]:
    """Comma- or line-separated values, bullets dropped."""
    found: list[str] = []
    for line in text.splitlines():
        for part in line.split(","):
            item = part.strip().lstrip("-*").strip()
            if item and item not in found:
                found.append(item)
    return found
