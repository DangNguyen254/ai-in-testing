"""Ticket source interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict


class TicketSourceError(RuntimeError):
    """A ticket could not be fetched. The message is safe to show to the user."""


class TicketNotFoundError(TicketSourceError):
    pass


class RateLimitError(TicketSourceError):
    pass


class RawTicket(BaseModel):
    """A ticket exactly as the source returned it, before normalization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    ref: str
    payload: dict[str, Any]


class TicketSource(ABC):
    """Fetches raw tickets from one system (GitHub, a Jira export, ...)."""

    name: str

    @abstractmethod
    def fetch(self, ref: str) -> RawTicket:
        """Fetch one ticket by a source-specific reference (e.g. ``owner/repo#123``)."""
