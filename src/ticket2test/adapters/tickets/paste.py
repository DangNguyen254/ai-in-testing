"""Pasted tickets: one Markdown file per ticket, filled in by hand from the ticket tracker
(for when its API can't be used). Never makes network calls.

The file has fixed ``##`` sections (see ``TEMPLATE``). Attachments are local files named in
the ``## Attachments`` section, one per line, relative to the ticket file; text, Markdown and
CSV files are read, others are only listed.
"""

from __future__ import annotations

import re
from pathlib import Path

from ticket2test.adapters.tickets.base import RawTicket, TicketNotFoundError, TicketSource

TEMPLATE = """\
# {key}: <title>

## Type

## Epic

## Components

## Labels

## Description

## Steps to reproduce

## Expected

## Actual

## Acceptance criteria

## Test plan
<!-- Paste the part of the linked test plan for this ticket: its steps and expected results. -->

## Attachments
<!-- Local files, one per line, relative to this file: .md, .txt, .csv are read. -->

## Comments
<!-- Separate comments with a line containing only --- -->

## Links
<!-- One URL per line: MRs, test plans, docs. They are recorded, never opened. -->
"""

READABLE = (".md", ".txt", ".csv")
_ATTACHMENTS = re.compile(r"^##\s+attachments?\s*$", re.IGNORECASE)


class PastedTicketSource(TicketSource):
    """Reads ``<folder>/<ref>.md``, or ``ref`` itself when it is a path to a Markdown file."""

    name = "paste"

    def __init__(self, folder: Path, max_attachment_chars: int = 20000) -> None:
        self._folder = folder
        self._max = max_attachment_chars

    def fetch(self, ref: str) -> RawTicket:
        path = Path(ref) if ref.endswith(".md") else self._folder / f"{ref}.md"
        if not path.is_file():
            raise TicketNotFoundError(f"Pasted ticket not found: {path}")
        text = path.read_text(encoding="utf-8")
        attachments: list[dict[str, str | None]] = []
        for name in attachment_names(text):
            target = (path.parent / name).resolve()
            body: str | None = None
            if target.suffix.lower() in READABLE and target.is_file():
                body = target.read_text(encoding="utf-8", errors="replace")[: self._max]
            attachments.append({"name": name, "text": body})
        key = path.stem
        return RawTicket(
            source=self.name,
            ref=key,
            payload={"path": str(path), "text": text, "attachments": attachments},
        )


def attachment_names(text: str) -> list[str]:
    """The non-empty lines of the ``## Attachments`` section (bullets and comments dropped)."""
    names: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = bool(_ATTACHMENTS.match(line.strip()))
            continue
        item = line.strip().lstrip("-*").strip()
        if inside and item and not item.startswith("<!--"):
            names.append(item)
    return names
