"""Jira ticket source stub: reads an exported JSON file. Never makes network calls.

Accepted file shapes (as produced by the Jira REST API / exports):
- a single issue object: ``{"key": "PROJ-1", "fields": {...}}``
- a search result: ``{"issues": [{...}, ...]}``
- a plain list of issue objects
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ticket2test.adapters.tickets.base import (
    RawTicket,
    TicketNotFoundError,
    TicketSource,
    TicketSourceError,
)


class JiraExportSource(TicketSource):
    name = "jira"

    def __init__(self, export_path: Path) -> None:
        self._path = export_path

    def fetch(self, ref: str) -> RawTicket:
        issues = self._load_issues()
        for issue in issues:
            if issue.get("key") == ref:
                return RawTicket(source=self.name, ref=ref, payload=issue)
        raise TicketNotFoundError(f"Issue {ref!r} not found in {self._path}")

    def _load_issues(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise TicketSourceError(f"Jira export file not found: {self._path}") from exc
        except json.JSONDecodeError as exc:
            raise TicketSourceError(f"Jira export is not valid JSON: {self._path}: {exc}") from exc

        if isinstance(data, dict) and isinstance(data.get("issues"), list):
            items: list[Any] = data["issues"]
        elif isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            raise TicketSourceError(f"Unrecognized Jira export shape in {self._path}")
        return [item for item in items if isinstance(item, dict)]
