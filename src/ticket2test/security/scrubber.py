"""Basic secret scrubber: regex-based redaction for prompt input and generated output.

This is a safety net, not a guarantee. Matches are replaced with ``[REDACTED:<kind>]``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    # Index of the group to redact; 0 = whole match. Other groups are kept (e.g. "Bearer ").
    group: int = 0


_SECRET_WORDS = (
    r"password|passwd|pwd|passphrase|secret|client[_-]?secret|api[_-]?key|apikey|"
    r"access[_-]?key|secret[_-]?key|account[_-]?key|access[_-]?token|auth[_-]?token|"
    r"refresh[_-]?token|private[_-]?key"
)

_RULES: tuple[_Rule, ...] = (
    _Rule(
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
            re.DOTALL,
        ),
    ),
    _Rule("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    _Rule("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_\w{22,})")),
    _Rule("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    _Rule("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    _Rule("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    _Rule("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    _Rule(
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ),
    _Rule(
        "bearer_token",
        re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{16,})"),
        group=2,
    ),
    _Rule(
        "basic_auth",
        re.compile(r"(?i)(authorization\s*:\s*basic\s+)([A-Za-z0-9+/=]{8,})"),
        group=2,
    ),
    # Password in URL userinfo (between "user:" and "@host"): only the password is redacted.
    _Rule(
        "password_in_url",
        re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:)([^\s@/]{1,256})(@)"),
        group=2,
    ),
    # password=..., "api_key": "...", Pwd=...; (connection strings). Value is redacted.
    _Rule(
        "credential_assignment",
        re.compile(
            rf"(?i)\b((?:{_SECRET_WORDS}))(\"?\s*[:=]\s*[\"']?)([^\s\"',;&]{{4,}})",
        ),
        group=3,
    ),
)


@dataclass(frozen=True)
class ScrubResult:
    text: str
    counts: Counter[str] = field(default_factory=Counter)

    @property
    def redacted(self) -> int:
        return sum(self.counts.values())


def scrub(text: str) -> ScrubResult:
    counts: Counter[str] = Counter()
    for rule in _RULES:
        text = rule.pattern.sub(_replacer(rule, counts), text)
    return ScrubResult(text=text, counts=counts)


def scrub_text(text: str) -> str:
    return scrub(text).text


def _replacer(rule: _Rule, counts: Counter[str]) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        return _redact(match, rule, counts)

    return replace


def _redact(match: re.Match[str], rule: _Rule, counts: Counter[str]) -> str:
    value = match.group(rule.group)
    if value.startswith("[REDACTED:"):
        return match.group(0)
    counts[rule.kind] += 1
    placeholder = f"[REDACTED:{rule.kind}]"
    if rule.group == 0:
        return placeholder
    start, end = match.span(rule.group)
    whole_start = match.start(0)
    whole = match.group(0)
    return whole[: start - whole_start] + placeholder + whole[end - whole_start :]


_SECRET_NAME = re.compile(rf"(?i)\w*(?:{_SECRET_WORDS})\w*")
_LITERAL = re.compile(  # a string literal: prefix and quote, body, closing quote
    r"(?s)^(?P<open>[rRbBuUfF]{0,2}(?:\"\"\"|'''|\"|'))(?P<body>.*)(?P<close>\"\"\"|'''|\"|')$"
)


def scrub_code(code: str) -> ScrubResult:
    """Scrub Python source without breaking it: only string literals and comments are scrubbed.

    A secret in source code is always a literal (or sits in a comment); an expression such as
    ``password=self.params["password"]`` is not a secret, and redacting part of it would leave
    code that doesn't parse. Code that doesn't tokenize is scrubbed as plain text.
    """
    import io
    import tokenize

    kinds = {tokenize.STRING, tokenize.COMMENT}
    kinds |= {getattr(tokenize, "FSTRING_MIDDLE", tokenize.STRING)}  # Python 3.12+
    layout = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return scrub(code)
    lines = code.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    counts: Counter[str] = Counter()
    pieces: list[tuple[int, int, str]] = []
    meaningful = [t for t in tokens if t.type not in layout]
    keyed: set[int] = set()  # string tokens assigned to, or keyed by, a secret-looking name
    for i, token in enumerate(meaningful):
        if token.type == tokenize.STRING and i >= 2 and meaningful[i - 1].string in ("=", ":"):
            key = meaningful[i - 2].string.strip("\"'")
            if _SECRET_NAME.fullmatch(key):
                keyed.add(id(token))
    for token in tokens:
        if token.type not in kinds:
            continue
        begin = starts[token.start[0] - 1] + token.start[1]
        end = starts[token.end[0] - 1] + token.end[1]
        if id(token) in keyed:
            literal = _LITERAL.match(code[begin:end])
            if literal and len(literal.group("body")) >= 4:
                counts["credential_assignment"] += 1
                body = "[REDACTED:credential_assignment]"
                pieces.append((begin, end, literal.group("open") + body + literal.group("close")))
                continue
        found = scrub(code[begin:end])
        if found.counts:
            counts.update(found.counts)
            pieces.append((begin, end, found.text))
    for begin, end, text in reversed(pieces):
        code = code[:begin] + text + code[end:]
    return ScrubResult(text=code, counts=counts)
