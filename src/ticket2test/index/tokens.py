"""Tokenization for keyword search: identifiers are split into words.

``get_HTTPResponse_code`` -> ``get``, ``http``, ``response``, ``code`` (plus the whole name
``get_httpresponse_code`` so exact identifier matches score higher).
"""

from __future__ import annotations

import keyword
import re

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Acronym followed by a capitalized word ("HTTPServer" -> HTTP, Server), capitalized or
# lowercase words, remaining acronyms, digit runs.
_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_STOPWORDS = frozenset(
    {*keyword.kwlist, "self", "cls", "the", "and", "for", "with", "this", "that", "none"}
)


def split_identifier(name: str) -> list[str]:
    """Split snake_case / CamelCase / acronyms / digits into lowercase words."""
    return [part.lower() for chunk in name.split("_") for part in _PART.findall(chunk)]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for identifier in _IDENTIFIER.findall(text):
        parts = split_identifier(identifier)
        if len(parts) > 1:
            whole = identifier.strip("_").lower()
            if whole not in _STOPWORDS:
                tokens.append(whole)
        tokens.extend(p for p in parts if len(p) > 1 and p not in _STOPWORDS)
    return tokens
