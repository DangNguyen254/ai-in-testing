"""RawTicket -> Ticket, per source. Rule-based only; missing data stays missing."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from ticket2test.adapters.tickets.base import RawTicket
from ticket2test.config import Settings
from ticket2test.models.ticket import Comment, SourceInfo, Ticket
from ticket2test.normalize.jira_markup import jira_to_markdown
from ticket2test.normalize.markdown import (
    Line,
    extract_urls,
    lines_to_text,
    markdown_to_text,
    split_lines,
    strip_inline_code,
)
from ticket2test.normalize.sections import Sections, extract_sections, split_steps

_ISSUE_REF = re.compile(r"(?<![\w/#&])(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<number>\d+)\b")


class NormalizationError(ValueError):
    """The raw payload is not usable (e.g. it has no title)."""


def normalize(raw: RawTicket, settings: Settings | None = None) -> Ticket:
    settings = settings or Settings()
    if raw.source == "github":
        return normalize_github(raw, settings)
    if raw.source == "jira":
        return normalize_jira(raw, settings)
    if raw.source == "paste":
        from ticket2test.normalize.paste import PasteError, normalize_paste

        try:
            return normalize_paste(raw, settings)
        except PasteError as exc:
            raise NormalizationError(str(exc)) from exc
    raise NormalizationError(f"Unknown ticket source: {raw.source!r}")


# --- GitHub ----------------------------------------------------------------------------------


def normalize_github(raw: RawTicket, settings: Settings) -> Ticket:
    issue = _as_dict(raw.payload.get("issue"))
    title = str(issue.get("title") or "").strip()
    if not title:
        raise NormalizationError(f"GitHub issue {raw.ref} has no title")

    owner_repo = raw.ref.split("#", 1)[0]
    body_lines = split_lines(str(issue.get("body") or ""))
    sections = extract_sections(body_lines)

    raw_comments = [_as_dict(c) for c in raw.payload.get("comments") or []]
    total_comments = max(int(issue.get("comments") or 0), len(raw_comments))
    comments = [
        _comment(
            author=_as_dict(c.get("user")).get("login"),
            markdown=str(c.get("body") or ""),
            created_at=c.get("created_at"),
            max_chars=settings.normalize.max_comment_chars,
        )
        for c in raw_comments
    ]
    kept = select_comments(comments, settings.normalize.max_comments)

    prefixes = settings.tickets.github.component_label_prefixes
    labels = [str(_as_dict(label).get("name", "")) for label in issue.get("labels") or []]
    labels = [label for label in labels if label]
    components = [
        label[len(prefix) :].strip()
        for label in labels
        for prefix in prefixes
        if label.startswith(prefix) and label[len(prefix) :].strip()
    ]

    url = issue.get("html_url")
    comment_lines = [line for c in raw_comments for line in split_lines(str(c.get("body") or ""))]
    links = _github_links(body_lines + comment_lines, owner_repo, exclude=url)

    return Ticket(
        id=raw.ref,
        title=title,
        description=markdown_to_text_or_none(body_lines),
        steps_to_reproduce=sections.steps,
        expected=sections.expected,
        actual=sections.actual,
        components=components,
        labels=labels,
        comments=kept,
        comments_omitted=total_comments - len(kept),
        links=links,
        source=SourceInfo(system="github", ref=raw.ref, url=str(url) if url else None),
    )


def _github_links(lines: list[Line], owner_repo: str, exclude: Any) -> list[str]:
    found: dict[str, None] = dict.fromkeys(extract_urls(lines))
    for line in lines:
        if line.in_code:
            continue
        for match in _ISSUE_REF.finditer(strip_inline_code(line.text)):
            repo = match.group("repo") or owner_repo
            found.setdefault(f"https://github.com/{repo}/issues/{match.group('number')}", None)
    return [link for link in found if link != exclude]


# --- Jira ------------------------------------------------------------------------------------


def normalize_jira(raw: RawTicket, settings: Settings) -> Ticket:
    issue = raw.payload
    fields = _as_dict(issue.get("fields"))
    key = str(issue.get("key") or raw.ref)
    title = str(fields.get("summary") or "").strip()
    if not title:
        raise NormalizationError(f"Jira issue {key} has no summary")

    jira = settings.tickets.jira
    body_lines = split_lines(jira_to_markdown(fields.get("description")))
    sections = extract_sections(body_lines)
    sections = _apply_field_map(sections, fields, jira.field_map)

    raw_comments = [_as_dict(c) for c in _as_dict(fields.get("comment")).get("comments") or []]
    comments = [
        _comment(
            author=_as_dict(c.get("author")).get("displayName"),
            markdown=jira_to_markdown(c.get("body")),
            created_at=c.get("created"),
            max_chars=settings.normalize.max_comment_chars,
        )
        for c in raw_comments
    ]
    kept = select_comments(comments, settings.normalize.max_comments)
    total_comments = max(int(_as_dict(fields.get("comment")).get("total") or 0), len(comments))

    browse = jira.browse_url.rstrip("/") if jira.browse_url else _browse_from_self(issue)
    links: dict[str, None] = dict.fromkeys(extract_urls(body_lines))
    for link in fields.get("issuelinks") or []:
        link = _as_dict(link)
        other = _as_dict(link.get("outwardIssue") or link.get("inwardIssue")).get("key")
        if other:
            links.setdefault(f"{browse}/{other}" if browse else str(other), None)

    return Ticket(
        id=key,
        title=title,
        description=markdown_to_text_or_none(body_lines),
        steps_to_reproduce=sections.steps,
        expected=sections.expected,
        actual=sections.actual,
        components=[str(_as_dict(c).get("name")) for c in fields.get("components") or [] if c],
        labels=[str(label) for label in fields.get("labels") or []],
        comments=kept,
        comments_omitted=total_comments - len(kept),
        links=list(links),
        source=SourceInfo(system="jira", ref=key, url=f"{browse}/{key}" if browse else None),
    )


def _apply_field_map(
    sections: Sections, fields: dict[str, Any], field_map: dict[Any, str]
) -> Sections:
    """Dedicated Jira fields (if configured and non-empty) win over description sections."""
    result = Sections(sections.steps, sections.expected, sections.actual)
    for target, field_id in field_map.items():
        lines = split_lines(jira_to_markdown(fields.get(field_id)))
        if not any(line.text.strip() for line in lines):
            continue
        if target == "steps_to_reproduce":
            result.steps = split_steps(lines)
        elif target == "expected":
            result.expected = lines_to_text(lines) or None
        elif target == "actual":
            result.actual = lines_to_text(lines) or None
    return result


def _browse_from_self(issue: dict[str, Any]) -> str | None:
    self_url = issue.get("self")
    if not isinstance(self_url, str):
        return None
    parts = urlsplit(self_url)
    return f"{parts.scheme}://{parts.netloc}/browse" if parts.scheme and parts.netloc else None


# --- Shared ----------------------------------------------------------------------------------


def select_comments(comments: Sequence[Comment], max_comments: int) -> list[Comment]:
    """Keep all comments if they fit; otherwise the first and the most recent ones."""
    if len(comments) <= max_comments:
        return list(comments)
    head = math.ceil(max_comments / 2)
    tail = max_comments - head
    return list(comments[:head]) + (list(comments[-tail:]) if tail else [])


def truncate_text(text: str, max_chars: int) -> str:
    """Cut at a line boundary when possible and say how much was dropped."""
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n", 0, max_chars)
    if cut < max_chars // 2:
        cut = max_chars
    return f"{text[:cut].rstrip()}\n[... truncated {len(text) - cut} characters]"


def markdown_to_text_or_none(lines: list[Line]) -> str | None:
    return lines_to_text(lines) or None


def _comment(author: Any, markdown: str, created_at: Any, max_chars: int) -> Comment:
    return Comment(
        author=str(author) if author else None,
        body=truncate_text(markdown_to_text(markdown), max_chars),
        created_at=_parse_datetime(created_at),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    # Jira uses "+0000" offsets; fromisoformat wants "+00:00".
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
