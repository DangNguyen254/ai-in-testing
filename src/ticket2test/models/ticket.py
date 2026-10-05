"""Normalized ticket: the only ticket shape the rest of the pipeline sees."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    system: Literal["github", "jira"]
    ref: str
    url: str | None = None


class Comment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    author: str | None = None
    body: str
    created_at: datetime | None = None


class Ticket(BaseModel):
    """A source-independent bug ticket.

    Fields the source did not provide are ``None`` or empty lists, never invented text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    description: str | None = None
    steps_to_reproduce: list[str] = Field(default_factory=list)
    expected: str | None = None
    actual: str | None = None
    components: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)
    comments_omitted: int = Field(default=0, ge=0)
    links: list[str] = Field(default_factory=list)
    source: SourceInfo
