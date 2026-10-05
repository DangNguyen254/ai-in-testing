"""Rule-based Markdown -> plain text.

Prose loses its markup (headings, emphasis, link syntax, HTML tags, template comments).
Fenced code blocks are kept verbatim, fences included: they are usually the reproduction.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ORPHAN_COMMENT_LINE = re.compile(r"^\s*(<!--|-->)\s*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BLOCKQUOTE = re.compile(r"^\s*>\s?")
_HRULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")

_INLINE_CODE = re.compile(r"(`+)(.+?)\1")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
# Only well-known HTML tags, so text like "<Request('GET', ...)>" survives.
_HTML_TAG = re.compile(
    r"</?(?:details|summary|p|div|span|img|sub|sup|b|i|em|strong|code|pre|a|ul|ol|li|"
    r"table|thead|tbody|tr|td|th|h[1-6]|hr|kbd|blockquote|picture|source|video|center)"
    r"(?:\s[^<>]*)?/?>",
    re.IGNORECASE,
)

_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
_URL_TRAILING = ".,;:!?*_"


@dataclass(frozen=True)
class Line:
    text: str
    in_code: bool  # inside a fenced code block (fence lines included)


def split_lines(markdown: str) -> list[Line]:
    """Split Markdown into lines tagged as code or prose. HTML comments are removed from prose."""
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    out: list[Line] = []
    prose: list[str] = []

    def flush_prose() -> None:
        if prose:
            cleaned = _HTML_COMMENT.sub("", "\n".join(prose))
            out.extend(
                Line(t, False) for t in cleaned.split("\n") if not _ORPHAN_COMMENT_LINE.match(t)
            )
            prose.clear()

    fence: str | None = None
    for raw in markdown.split("\n"):
        match = _FENCE.match(raw)
        if fence is None:
            if match:
                flush_prose()
                fence = match.group(1)
                out.append(Line(raw.rstrip(), True))
            else:
                prose.append(raw)
        else:
            out.append(Line(raw.rstrip(), True))
            # A closing fence uses the same character, is at least as long, and has no info string.
            closing = match.group(1) if match else ""
            if (
                closing
                and closing == raw.strip()
                and closing[0] == fence[0]
                and len(closing) >= len(fence)
            ):
                fence = None
    flush_prose()
    return out


def inline_to_text(text: str) -> str:
    """Strip inline Markdown/HTML markup from one prose line."""
    codes: list[str] = []

    def stash(match: re.Match[str]) -> str:
        codes.append(match.group(2).strip())
        return f"\x00{len(codes) - 1}\x00"

    text = _INLINE_CODE.sub(stash, text)
    text = _IMAGE.sub(lambda m: f"{m.group(1)} ({m.group(2)})".strip(), text)
    text = _LINK.sub(lambda m: _link_text(m.group(1), m.group(2)), text)
    text = _AUTOLINK.sub(r"\1", text)
    text = _BR.sub("\n", text)
    text = _HTML_TAG.sub("", text)
    text = _BOLD.sub(r"\1", text)
    text = _ITALIC.sub(r"\1", text)
    text = _STRIKE.sub(r"\1", text)
    text = html.unescape(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def _link_text(label: str, url: str) -> str:
    return url if label.strip() == url else f"{label} ({url})"


def prose_line_to_text(text: str) -> str:
    """Convert one prose line: block-level markers, then inline markup."""
    if _HRULE.match(text):
        return ""
    heading = _HEADING.match(text)
    if heading:
        text = heading.group(1)
    text = _BLOCKQUOTE.sub("", text)
    return inline_to_text(text).rstrip()


def lines_to_text(lines: list[Line]) -> str:
    rendered = [line.text if line.in_code else prose_line_to_text(line.text) for line in lines]
    return collapse_blank_lines("\n".join(rendered))


def collapse_blank_lines(text: str) -> str:
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def markdown_to_text(markdown: str) -> str:
    return lines_to_text(split_lines(markdown))


def strip_inline_code(text: str) -> str:
    """Remove inline code spans (their contents are example data, not references)."""
    return _INLINE_CODE.sub(" ", text)


def extract_urls(lines: list[Line]) -> list[str]:
    """URLs mentioned in prose (not in code blocks or inline code), in order, de-duplicated."""
    seen: dict[str, None] = {}
    for line in lines:
        if line.in_code:
            continue
        for match in _URL.finditer(strip_inline_code(line.text)):
            seen.setdefault(match.group(0).rstrip(_URL_TRAILING), None)
    return list(seen)
