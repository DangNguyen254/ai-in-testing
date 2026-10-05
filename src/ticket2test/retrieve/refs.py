"""References inside a chunk's code, for AST-style expansion (callees and page-object chains)."""

from __future__ import annotations

import builtins
import keyword
import re

_ATTR_CALL = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_BARE_CALL = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_SELF_CHAIN = re.compile(r"self((?:\.[A-Za-z_][A-Za-z0-9_]*(?:\(\))?)+)")
_KEYWORDS = frozenset(keyword.kwlist) | {"self", "cls", "super"}
_BUILTINS = frozenset(dir(builtins))


def called_names(code: str) -> list[str]:
    """Names called in the code, in order. Bare builtins (``len(``) are dropped; methods
    with a builtin's name (``page.open(``) are kept."""
    found: list[tuple[int, str]] = []
    for match in _ATTR_CALL.finditer(code):
        if match.group(1) not in _KEYWORDS:
            found.append((match.start(1), match.group(1)))
    for match in _BARE_CALL.finditer(code):
        name = match.group(1)
        if name not in _KEYWORDS and name not in _BUILTINS:
            found.append((match.start(1), name))
    seen: dict[str, None] = {}
    for _, name in sorted(found):
        seen.setdefault(name, None)
    return list(seen)


def self_chains(code: str) -> list[list[str]]:
    """Attribute chains on ``self``: ``self.nav.users.invite.open().invite(`` ->
    ["nav", "users", "invite", "open()", "invite"]. A call with arguments ends the chain."""
    chains: list[list[str]] = []
    seen: set[str] = set()
    for match in _SELF_CHAIN.finditer(code):
        text = match.group(1)
        if text in seen:
            continue
        seen.add(text)
        steps = [s for s in text.split(".") if s]
        if len(steps) >= 2:
            chains.append(steps)
    return chains
