"""Jira rich text -> Markdown, so one Markdown pipeline handles every source.

Supports Atlassian Document Format (ADF, Jira Cloud API v3) and basic wiki markup (API v2).
"""

from __future__ import annotations

import re
from typing import Any

_INDENT = "  "


def jira_to_markdown(value: Any) -> str:
    """Convert a Jira rich-text field (ADF dict, wiki string, or None) to Markdown."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return adf_to_markdown(value)
    if isinstance(value, str):
        return wiki_to_markdown(value)
    return str(value)


# --- ADF -----------------------------------------------------------------------------------


def adf_to_markdown(node: dict[str, Any]) -> str:
    return _blocks(node.get("content") or []) if node.get("type") == "doc" else _block(node)


def _blocks(nodes: list[Any]) -> str:
    rendered = (_block(n) for n in nodes if isinstance(n, dict))
    return "\n\n".join(r for r in rendered if r.strip())


def _block(node: dict[str, Any]) -> str:
    kind = node.get("type")
    attrs = node.get("attrs") or {}
    content = node.get("content") or []

    if kind == "paragraph":
        return _inline(content)
    if kind == "heading":
        level = min(max(int(attrs.get("level", 1)), 1), 6)
        return f"{'#' * level} {_inline(content)}"
    if kind == "codeBlock":
        lang = attrs.get("language") or ""
        code = "".join(n.get("text", "") for n in content if isinstance(n, dict))
        return f"```{lang}\n{code}\n```"
    if kind in ("bulletList", "orderedList"):
        start = int(attrs.get("order", 1))
        items = []
        for idx, item in enumerate(c for c in content if isinstance(c, dict)):
            marker = f"{start + idx}." if kind == "orderedList" else "-"
            body = _blocks(item.get("content") or []).split("\n")
            items.append(f"{marker} {body[0]}" + "".join(f"\n{_INDENT}{ln}" for ln in body[1:]))
        return "\n".join(items)
    if kind == "blockquote":
        return "\n".join(f"> {ln}" for ln in _blocks(content).split("\n"))
    if kind == "rule":
        return "---"
    if kind == "table":
        rows = []
        for row in content:
            cells = [_blocks(c.get("content") or []) for c in row.get("content") or []]
            rows.append(" | ".join(cell.replace("\n", " ") for cell in cells))
        return "\n".join(rows)
    if kind in ("mediaSingle", "mediaGroup", "media"):
        return "[attachment]"
    if kind in ("text", "hardBreak", "mention", "emoji", "inlineCard", "status", "date"):
        return _inline([node])
    # panel, expand, layoutSection, ... and unknown containers: render children.
    return _blocks(content) if content else str(node.get("text", ""))


def _inline(nodes: list[Any]) -> str:
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        attrs = node.get("attrs") or {}
        if kind == "text":
            parts.append(_apply_marks(str(node.get("text", "")), node.get("marks") or []))
        elif kind == "hardBreak":
            parts.append("\n")
        elif kind == "mention":
            parts.append(str(attrs.get("text") or "@user"))
        elif kind == "emoji":
            parts.append(str(attrs.get("text") or attrs.get("shortName") or ""))
        elif kind in ("inlineCard", "blockCard"):
            parts.append(str(attrs.get("url", "")))
        elif kind == "status":
            parts.append(str(attrs.get("text", "")))
        elif kind == "date":
            parts.append(str(attrs.get("timestamp", "")))
        elif node.get("content"):
            parts.append(_inline(node["content"]))
    return "".join(parts)


def _apply_marks(text: str, marks: list[Any]) -> str:
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        kind = mark.get("type")
        if kind == "code":
            text = f"`{text}`"
        elif kind == "strong":
            text = f"**{text}**"
        elif kind == "em":
            text = f"*{text}*"
        elif kind == "link":
            href = (mark.get("attrs") or {}).get("href")
            if href:
                text = f"[{text}]({href})"
    return text


# --- Wiki markup ---------------------------------------------------------------------------

_WIKI_CODE_OPEN = re.compile(r"^\s*\{(code|noformat)(?::([^}]*))?\}\s*(.*)$")
_WIKI_CODE_CLOSE = re.compile(r"^(.*?)\{(code|noformat)\}\s*$")
_WIKI_HEADING = re.compile(r"^\s*h([1-6])\.\s+(.*)$")
_WIKI_LIST = re.compile(r"^\s*([*#]+|-)\s+(.*)$")
_WIKI_LINK = re.compile(r"\[([^|\]]+)\|([^\]]+)\]")
_WIKI_BARE_LINK = re.compile(r"\[((?:https?|mailto):[^\]|]+)\]")
_WIKI_MONO = re.compile(r"\{\{(.+?)\}\}")
_WIKI_BQ = re.compile(r"^\s*bq\.\s+")


def wiki_to_markdown(text: str) -> str:
    out: list[str] = []
    in_code = False
    for line in text.replace("\r\n", "\n").split("\n"):
        if in_code:
            close = _WIKI_CODE_CLOSE.match(line)
            if close:
                if close.group(1):
                    out.append(close.group(1))
                out.append("```")
                in_code = False
            else:
                out.append(line)
            continue

        opening = _WIKI_CODE_OPEN.match(line)
        if opening:
            lang = _code_language(opening.group(2) or "")
            rest = opening.group(3)
            out.append(f"```{lang}")
            same_line_close = _WIKI_CODE_CLOSE.match(rest)
            if same_line_close:
                out.extend(
                    [same_line_close.group(1), "```"] if same_line_close.group(1) else ["```"]
                )
            else:
                if rest:
                    out.append(rest)
                in_code = True
            continue

        out.append(_wiki_line(line))
    if in_code:
        out.append("```")
    return "\n".join(out)


def _code_language(params: str) -> str:
    for part in params.split("|"):
        key, _, value = part.partition("=")
        if value and key.strip() == "language":
            return value.strip()
        if not value and part.strip() and "=" not in part:
            return part.strip()
    return ""


def _wiki_line(line: str) -> str:
    if line.strip() in ("{quote}", "{panel}"):
        return ""
    heading = _WIKI_HEADING.match(line)
    if heading:
        line = f"{'#' * int(heading.group(1))} {heading.group(2)}"
    else:
        listing = _WIKI_LIST.match(line)
        if listing:
            markers = listing.group(1)
            bullet = "1." if markers[-1] == "#" else "-"
            line = f"{_INDENT * (len(markers) - 1)}{bullet} {listing.group(2)}"
    line = _WIKI_BQ.sub("> ", line)
    line = _WIKI_LINK.sub(r"[\1](\2)", line)
    line = _WIKI_BARE_LINK.sub(r"\1", line)
    return _WIKI_MONO.sub(r"`\1`", line)
