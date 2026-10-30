"""Missing pieces: helpers or page-object members a new test needs that the suite lacks.

Candidates come from two places: names the generated test uses that don't exist (after repair),
and the retrieval investigator's hints. Code checks every candidate before anything acts on it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MissingKind = Literal["page_object_member", "helper", "fixture"]


class MissingPiece(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: MissingKind
    owner: str  # a class (name or qualname), a page-object chain, or "" for a module function
    name: str = Field(min_length=1, max_length=120)
    needed_for: str = Field(max_length=300)  # the test line or draft step that needs it
    # generated: the code calls it; investigator: a retrieval hint; noted: the generating model
    # said the test needs it (and left the check out)
    source: Literal["generated", "investigator", "noted"]


class GapVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    piece: MissingPiece
    status: Literal["missing", "exists", "close_match", "owner_unknown", "not_test_side"]
    owner_class: str | None = None  # the resolved owner (class qualname)
    found: str | None = None  # status "exists": where it is defined
    close: list[str] = Field(default_factory=list)  # existing names that may be the same thing
    reason: str = ""
