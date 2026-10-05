"""BM25 keyword search over chunks (tokens from ``index/tokens.py``)."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from ticket2test.index.tokens import tokenize
from ticket2test.models.chunk import Chunk, ChunkKind


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float


class SearchIndex:
    def __init__(self, chunks: list[Chunk], tokens: dict[str, list[str]]) -> None:
        self._chunks = chunks
        corpus = [tokens.get(c.id, []) for c in chunks]
        # rank_bm25 divides by the corpus size; an empty corpus has nothing to rank.
        self._bm25 = BM25Okapi(corpus) if any(corpus) else None

    def search(
        self, query: str, top_k: int = 10, kinds: Collection[ChunkKind] | None = None
    ) -> list[SearchHit]:
        query_tokens = tokenize(query)
        if self._bm25 is None or not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        ranked = sorted(
            (
                (float(score), index)
                for index, score in enumerate(scores)
                if score > 0 and (not kinds or self._chunks[index].kind in kinds)
            ),
            key=lambda pair: (-pair[0], self._chunks[pair[1]].id),
        )
        return [SearchHit(self._chunks[i], score) for score, i in ranked[:top_k]]


def chunk_search_text(chunk: Chunk, name_boost: int) -> str:
    """What BM25 sees for a chunk: name (boosted), location, code, ids, markers, data."""
    parts = [" ".join([chunk.symbol_name] * name_boost), chunk.qualname, chunk.file_path]
    parts.append(chunk.code)
    parts.extend(chunk.test_ids)
    parts.extend(f"{m.name} {' '.join(map(str, m.args))}" for m in chunk.markers)
    parts.extend(_flatten(entry) for entry in chunk.data_entries.values())
    return "\n".join(parts)


def _flatten(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(f"{k} {_flatten(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value)
    return str(value)
