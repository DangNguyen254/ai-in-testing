"""Context building for generation: whole pieces, in priority order, within a token budget.

Pieces are never cut: a piece that doesn't fit is skipped and the next one is tried.
Required pieces (conventions doc, draft, template) must fit, or building fails.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ticket2test.index.catalog import SymbolCatalog
from ticket2test.models.chunk import Chunk


class ContextBudgetError(ValueError):
    """The required pieces alone exceed the token budget."""


@dataclass(frozen=True)
class Piece:
    title: str
    body: str
    chunk_id: str | None = None
    required: bool = False


@dataclass
class BuiltContext:
    pieces: list[Piece] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # titles that didn't fit
    tokens: int = 0

    @property
    def chunk_ids(self) -> list[str]:
        return [p.chunk_id for p in self.pieces if p.chunk_id]

    def render(self) -> str:
        return "\n\n".join(f"### {p.title}\n{p.body}" for p in self.pieces)


def estimate_tokens(text: str, chars_per_token: float) -> int:
    return math.ceil(len(text) / chars_per_token)


def build_context(pieces: list[Piece], max_tokens: int, chars_per_token: float) -> BuiltContext:
    """Add pieces in order while they fit. Required pieces must all fit."""

    def cost(piece: Piece) -> int:
        # Title, body, and the "### " header + blank-line separator that render() adds.
        return estimate_tokens(f"\n\n### {piece.title}\n{piece.body}", chars_per_token)

    total = sum(cost(p) for p in pieces if p.required)
    if total > max_tokens:
        raise ContextBudgetError(
            f"required context ({total} tokens est.) exceeds context.max_tokens ({max_tokens})"
        )
    included: set[int] = {i for i, p in enumerate(pieces) if p.required}
    skipped: list[str] = []
    for i, piece in enumerate(pieces):
        if piece.required:
            continue
        if total + cost(piece) <= max_tokens:
            included.add(i)
            total += cost(piece)
        else:
            skipped.append(piece.title)
    return BuiltContext(
        pieces=[p for i, p in enumerate(pieces) if i in included], skipped=skipped, tokens=total
    )


# --- pieces from retrieval -------------------------------------------------------------------


def chunk_piece(chunk: Chunk, label: str, required: bool = False) -> Piece:
    location = f"{chunk.file_path}:{chunk.start_line}"
    return Piece(
        f"{label}: {chunk.qualname} ({location})",
        f"```python\n{chunk.code}\n```",
        chunk.id,
        required,
    )


def template_piece(
    chunk: Chunk, entry_key: str, entry_json: str, scaffold: str | None = None
) -> Piece:
    """The template test, its class scaffold, and its entry (the base for new entries)."""
    sections = ", ".join(chunk.data_entries[entry_key])
    body = ""
    if scaffold:
        body += f"Class scaffold (copy unchanged; new class name):\n```python\n{scaffold}\n```\n"
    body += (
        f"```python\n{chunk.code}\n```\n"
        f"Base entry `{entry_key}` (from {chunk.data_file}; top-level sections: {sections}):\n"
        f"```json\n{entry_json.rstrip()}\n```"
    )
    return Piece(
        f"Template test: {chunk.qualname} ({chunk.file_path})", body, chunk.id, required=True
    )


def chains_piece(
    catalog: SymbolCatalog, page_object_qualnames: list[str], limit: int = 80
) -> Piece | None:
    """Page-object chains whose last step is on the given page objects (names only)."""
    wanted = set(page_object_qualnames)
    lines = [
        f"{c.chain}  ({c.kind})"
        for c in catalog.chains
        if c.owner in wanted or (c.type in wanted and c.kind != "method")
    ][:limit]
    if not lines:
        return None
    return Piece("Available page-object chains (self.<chain>)", "\n".join(lines))
