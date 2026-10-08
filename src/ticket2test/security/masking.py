"""Masking prompt-injection payloads, so our own LLM never reads them.

Test suites for an AI agent hold payloads written to manipulate a model ("Ignore previous
instructions and ..."). Tickets quote them too. Before any text reaches the LLM, the masker
replaces each payload with a token ``[[PAYLOAD_<n>]]`` and keeps the original. Afterwards the
caller restores the originals in the structured result: in plain strings, in JSON text, and in
Python string literals of generated code.

What counts as a payload:
- **Patterns:** a match of any configured regex (instruction-like phrasing). The masked span
  is the enclosing quoted string, or else the sentence around the match.
- **Keys:** the string value of a configured JSON key (e.g. ``"alt": "..."``), whatever it says.

The same payload always gets the same token for the lifetime of one masker.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from dataclasses import dataclass, field

TOKEN = re.compile(r"\[\[PAYLOAD_(\d+)\]\]")


@dataclass(frozen=True)
class Payload:
    token: str
    plain: str  # the text itself
    where: str  # "key 'alt'" or "instruction-like text"


@dataclass
class Masker:
    patterns: list[re.Pattern[str]]
    keys: list[str]
    min_chars: int = 1
    _by_plain: dict[str, Payload] = field(default_factory=dict)
    _by_token: dict[str, Payload] = field(default_factory=dict)

    @classmethod
    def from_config(cls, patterns: list[str], keys: list[str], min_chars: int = 1) -> Masker:
        return cls([re.compile(p, re.IGNORECASE) for p in patterns], list(keys), min_chars)

    @property
    def payloads(self) -> list[Payload]:
        return list(self._by_plain.values())  # in token order

    def originals(self) -> set[str]:
        return set(self._by_plain)

    # --- masking ------------------------------------------------------------------------

    def mask(self, text: str) -> str:
        """Mask key values (in JSON text) and instruction-like spans in any text."""
        if self.keys:
            text = self._mask_keys(text)
        return self._mask_patterns(text)

    def _mask_keys(self, text: str) -> str:
        keys = "|".join(re.escape(k) for k in self.keys)
        field_re = re.compile(rf'("(?:{keys})"\s*:\s*")((?:\\.|[^"\\])*)(")')

        def replace(match: re.Match[str]) -> str:
            raw = match.group(2)
            if len(raw) < self.min_chars or TOKEN.fullmatch(raw):
                return match.group(0)
            key = match.group(1).split('"')[1]
            payload = self._token_for(_json_decode(raw), f"key {key!r}")
            return match.group(1) + payload.token + match.group(3)

        return field_re.sub(replace, text)

    def _mask_patterns(self, text: str) -> str:
        for _ in range(1000):  # bounded: each round masks one span
            span = self._next_span(text)
            if span is None:
                return text
            start, end = span
            raw = text[start:end]
            plain = _json_decode(raw) if "\\" in raw else raw
            payload = self._token_for(plain, "instruction-like text")
            text = text[:start] + payload.token + text[end:]
        return text

    def _next_span(self, text: str) -> tuple[int, int] | None:
        for pattern in self.patterns:
            for match in pattern.finditer(text):
                if TOKEN.search(text[max(0, match.start() - 2) : match.end() + 2]):
                    continue
                return _enclosing(text, match.start(), match.end())
        return None

    def _token_for(self, plain: str, where: str) -> Payload:
        found = self._by_plain.get(plain)
        if found is None:
            found = Payload(f"[[PAYLOAD_{len(self._by_plain) + 1}]]", plain, where)
            self._by_plain[plain] = found
            self._by_token[found.token] = found
        return found

    def legend(self, text: str) -> str:
        """One line per token that occurs in ``text`` (for the prompt's legend)."""
        used = {m.group(0) for m in TOKEN.finditer(text)}
        return "\n".join(
            f"- {p.token}: {p.where}, {len(p.plain)} characters"
            for p in self.payloads
            if p.token in used
        )

    # --- unmasking ----------------------------------------------------------------------

    def unmask(self, text: str) -> str:
        """Plain text: tokens become the original text."""
        return TOKEN.sub(lambda m: self._plain(m) or m.group(0), text)

    def unmask_json_text(self, text: str) -> str:
        """JSON text: tokens (inside JSON strings) become the JSON-escaped original."""

        def replace(match: re.Match[str]) -> str:
            plain = self._plain(match)
            return (
                json.dumps(plain, ensure_ascii=False)[1:-1] if plain is not None else match.group(0)
            )

        return TOKEN.sub(replace, text)

    def unmask_code(self, code: str) -> str:
        """Python code: tokens inside string literals become the original, re-quoted safely.

        Tokens outside plain string literals (comments, f-strings) are left in place; the
        validator reports them.
        """
        if not TOKEN.search(code):
            return code
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
        except (tokenize.TokenError, SyntaxError):
            return code
        out = []
        for tok in tokens:
            if tok.type == tokenize.STRING and TOKEN.search(tok.string):
                tok = tok._replace(string=self._requote(tok.string))
            out.append(tok)
        return tokenize.untokenize(out)

    def _requote(self, literal: str) -> str:
        prefix = literal[: len(literal) - len(literal.lstrip("rRbBuUfF"))]
        if "f" in prefix.lower() or "b" in prefix.lower():
            return literal
        try:
            value = ast.literal_eval(literal)  # a literal only: never runs code
        except (ValueError, SyntaxError):
            return literal
        if not isinstance(value, str):
            return literal
        return json.dumps(self.unmask(value), ensure_ascii=False)

    def _plain(self, match: re.Match[str]) -> str | None:
        payload = self._by_token.get(match.group(0))
        return payload.plain if payload else None


_MAX_QUOTED = 400  # longer quoted text is a document, not a payload: mask the sentence


def _enclosing(text: str, start: int, end: int) -> tuple[int, int]:
    """The span to mask around a match at ``[start, end)``.

    A short quoted string around the match (a payload quoted in prose, or a whole data value)
    is masked whole. Otherwise, and inside long strings such as a ticket description held in
    JSON, only the sentence around the match is masked.
    """
    quoted = _quoted(text, start, end)
    if quoted is not None:
        return quoted
    return _sentence(text, start, end)


def _quoted(text: str, start: int, end: int) -> tuple[int, int] | None:
    left = _quote_before(text, start)
    if left is None:
        return None
    position, escaped = left
    right = _quote_after(text, end, escaped)
    if right is None:
        return None
    content_start = position + 1
    content_end = right - 1 if escaped else right
    content = text[content_start:content_end]
    if len(content) > _MAX_QUOTED:
        return None
    if not escaped and _has_break(content, start - content_start, end - content_start):
        return None  # several sentences in one value: mask only the one with the match
    return content_start, content_end


def _quote_before(text: str, index: int) -> tuple[int, bool] | None:
    """The nearest quote left of ``index`` on the line: (position, is it an escaped quote)."""
    i = index - 1
    while i >= 0 and index - i <= _MAX_QUOTED + 2:
        char = text[i]
        if char == "\n" or text.startswith("\\n", i):
            return None
        if char == '"':
            return i, i > 0 and text[i - 1] == "\\"
        i -= 1
    return None


def _quote_after(text: str, index: int, escaped: bool) -> int | None:
    """The matching quote right of ``index``: same kind (escaped or not), on the line."""
    i = index
    while i < len(text) and i - index <= _MAX_QUOTED + 2:
        char = text[i]
        if char == "\n" or text.startswith("\\n", i):
            return None
        if char == '"' and (i > 0 and text[i - 1] == "\\") == escaped:
            return i
        i += 1
    return None


def _has_break(content: str, start: int, end: int) -> bool:
    before, after = content[: max(start, 0)], content[end:]
    return bool(re.search(r"[.!?]\s", before) or re.search(r"[.!?]\s+\S", after))


_LEFT_BREAK = re.compile(r'\n|\\n|[.!?]\s|(?<!\\)"|\\"')
_RIGHT_BREAK = re.compile(r'[.!?](?=\s|$|\\n|\\"|")|\n|\\n|(?<!\\)"|\\"')


def _sentence(text: str, start: int, end: int) -> tuple[int, int]:
    left = 0
    for match in _LEFT_BREAK.finditer(text, 0, start):
        left = match.end()
    while left < start and text[left] == " ":
        left += 1
    right_match = _RIGHT_BREAK.search(text, end)
    if right_match is None:
        return left, len(text)
    right = right_match.end() if text[right_match.start()] in ".!?" else right_match.start()
    return left, right


def _json_decode(raw: str) -> str:
    try:
        value = json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw
    return value if isinstance(value, str) else raw
