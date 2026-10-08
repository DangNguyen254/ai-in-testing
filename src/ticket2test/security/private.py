"""Private terms: names that must never reach an external LLM or this repo.

``security.private_terms`` lists case-insensitive regexes (company, product and customer names,
internal hosts, ...). They belong in the private config or the environment
(``T2T_SECURITY__PRIVATE_TERMS``, a JSON list), never in this repo. Empty by default.

- prompts: ``PrivacyClient`` (``llm/privacy.py``) redacts every match before a request leaves;
- generated output: the validator's ``private`` check reports any match (or a leftover
  redaction mark) as an error;
- this repo: ``ticket2test privacy-scan`` checks the tracked files before a commit.

Reports name a term by its position in the list (``term #2``), never by its text, so a CI log
doesn't leak it. Redaction is one-way: list names that code doesn't need, not identifiers the
generated tests must reference.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

MARK = "[PRIVATE]"


@dataclass(frozen=True)
class Hit:
    term: int  # 1-based position in the configured list
    line: int  # 1-based


class PrivateTerms:
    def __init__(self, patterns: list[str]) -> None:
        self._patterns = [re.compile(p, re.IGNORECASE) for p in patterns if p.strip()]

    def __bool__(self) -> bool:
        return bool(self._patterns)

    def redact(self, text: str) -> tuple[str, int]:
        count = 0
        for pattern in self._patterns:
            text, n = pattern.subn(MARK, text)
            count += n
        return text, count

    def find(self, text: str) -> list[Hit]:
        hits: list[Hit] = []
        for n, pattern in enumerate(self._patterns, 1):
            for match in pattern.finditer(text):
                hits.append(Hit(term=n, line=text.count("\n", 0, match.start()) + 1))
        return sorted(hits, key=lambda h: (h.line, h.term))


def repo_files(root: Path) -> list[str]:
    """Files git would commit: tracked, plus untracked ones that aren't ignored."""
    args = ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"]
    out = subprocess.run(args, capture_output=True, text=True, check=True, encoding="utf-8")
    return sorted({line for line in out.stdout.splitlines() if line})


def scan_files(root: Path, files: list[str], terms: PrivateTerms) -> list[tuple[str, Hit]]:
    found: list[tuple[str, Hit]] = []
    for name in files:
        path = root / name
        try:
            if not path.is_file() or path.stat().st_size > _MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # binary or unreadable: not text to leak
            continue
        found += [(name, hit) for hit in terms.find(text)]
    return found


_MAX_BYTES = 5_000_000
