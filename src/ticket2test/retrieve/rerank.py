"""Deterministic, feature-based reranking with diversity rules.

Fused retrieval scores say "relevant"; they don't stop one file's methods from taking every
slot. This step re-scores candidates with a few explainable signals, then picks the top k
greedily with a per-file cap and a minimum number of tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ticket2test.config import RerankSettings
from ticket2test.index.tokens import tokenize
from ticket2test.models.chunk import Chunk


@dataclass
class Ranked:
    chunk: Chunk
    fused: float
    score: float
    features: dict[str, float]


def rerank(
    candidates: Sequence[tuple[Chunk, float, Sequence[str]]],
    identifiers: Sequence[str],
    ticket_text: str,
    k: int,
    settings: RerankSettings,
) -> list[Ranked]:
    """``candidates``: (chunk, fused score, reason details). Returns the selected top ``k``."""
    if not candidates:
        return []
    top_fused = max(score for _, score, _ in candidates) or 1.0
    wanted = set(identifiers)
    ticket_words = set(tokenize(ticket_text))

    scored: list[Ranked] = []
    for chunk, fused, details in candidates:
        features = {"fused": fused / top_fused}
        if settings.enabled:
            referenced = wanted & (set(chunk.refs.names) | {chunk.symbol_name})
            if referenced:
                features["identifiers"] = settings.identifier_weight * min(len(referenced), 3) / 3
            if chunk.symbol_name in wanted:
                features["definition"] = settings.definition_weight
            if chunk.kind == "test" and any(d.startswith("test of ") for d in details):
                features["test_link"] = settings.test_link_weight
            path_words = set(tokenize(chunk.file_path.replace("/", " ").replace(".py", "")))
            overlap = len(ticket_words & path_words - {"tests", "test", "src"})
            if overlap:
                features["path"] = settings.path_weight * min(overlap, 2) / 2
        score = sum(features.values())
        scored.append(
            Ranked(chunk, fused, round(score, 6), {k_: round(v, 4) for k_, v in features.items()})
        )

    scored.sort(key=lambda r: (-r.score, r.chunk.id))
    if not settings.enabled:
        return scored[:k]
    return _select(scored, k, settings.max_chunks_per_file, settings.min_tests)


def _select(ranked: list[Ranked], k: int, per_file: int, min_tests: int) -> list[Ranked]:
    chosen: list[Ranked] = []
    per_file_count: dict[str, int] = {}

    def fits(r: Ranked) -> bool:
        return per_file_count.get(r.chunk.file_path, 0) < per_file

    def take(r: Ranked) -> None:
        chosen.append(r)
        per_file_count[r.chunk.file_path] = per_file_count.get(r.chunk.file_path, 0) + 1

    # Reserve the best tests first (within the per-file cap), then fill by score.
    for r in [r for r in ranked if r.chunk.kind == "test"]:
        if sum(c.chunk.kind == "test" for c in chosen) >= min(min_tests, k):
            break
        if fits(r):
            take(r)
    for r in ranked:
        if len(chosen) >= k:
            break
        if r not in chosen and fits(r):
            take(r)
    # Not enough distinct files to fill k under the cap: relax it rather than return fewer.
    for r in ranked:
        if len(chosen) >= k:
            break
        if r not in chosen:
            take(r)
    chosen.sort(key=lambda r: (-r.score, r.chunk.id))
    return chosen
