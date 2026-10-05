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
