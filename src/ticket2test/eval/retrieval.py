"""Retrieval eval: recall@k and MRR against fix-PR files or linked tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import Settings
from ticket2test.eval.pairs import EvalCache, EvalPair, PairSet
from ticket2test.index.indexer import update_index
from ticket2test.llm.base import LLMClient
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve


class PairResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pair_id: str
    ticket: str
    unit: str  # "file" or "test"
    ground_truth: list[str]
    not_in_index: list[str] = Field(default_factory=list)
    retrieved: list[str]  # top-k units, in rank order (deduplicated)
    found: list[str]
    recall: float
    reciprocal_rank: float
    llm_calls: int = 0
    followup_rounds: int = 0


class SkippedPair(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pair_id: str
    reason: str


class RetrievalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_name: str
    k: int
    use_llm: bool
    created_at: datetime
    repo_path: str
    pairs: list[PairResult] = Field(default_factory=list)
    skipped: list[SkippedPair] = Field(default_factory=list)
    mean_recall: float | None = None
    mean_reciprocal_rank: float | None = None
    settings: dict[str, Any] = Field(default_factory=dict)  # retrieval config snapshot


def manifest_test_to_chunk_id(test: str) -> str:
    """``path::Class::test_x`` (pytest style) -> ``path::Class.test_x`` (chunk id)."""
    path, _, rest = test.partition("::")
    return f"{path}::{rest.replace('::', '.')}"


def evaluate_retrieval(
    pair_set: PairSet,
    project_root: Path,
    settings: Settings,
    client: LLMClient | None = None,
    cache: EvalCache | None = None,
    k: int | None = None,
) -> RetrievalReport:
    k = k or settings.retrieval.top_k
    settings = settings.model_copy(
        update={"retrieval": settings.retrieval.model_copy(update={"top_k": k})}
    )
    repo = project_root / pair_set.repo_path
    if not repo.is_dir():
        raise FileNotFoundError(f"{repo} not found. {pair_set.repo_clone or ''}".strip())
    index, _, _ = update_index(repo, settings)
    cache = cache or EvalCache(settings)
    use_llm = settings.retrieval.use_llm and client is not None
    report = RetrievalReport(
        set_name=pair_set.name,
        k=k,
        use_llm=use_llm,
        created_at=datetime.now(UTC),
        repo_path=pair_set.repo_path,
        settings=settings.retrieval.model_dump(mode="json"),
    )
    indexed_files = {path for path, record in index.files.items() if record.info is not None}
    chunk_ids = {c.id for c in index.chunks}

    for pair in pair_set.pairs:
        try:
            truth, unit = _ground_truth(pair_set, pair, cache)
        except Exception as exc:  # network / cache problems skip the pair, not the run
            report.skipped.append(SkippedPair(pair_id=pair.id, reason=f"ground truth: {exc}"))
            continue
        known = indexed_files if unit == "file" else chunk_ids
        present = [t for t in truth if t in known]
        if not present:
            report.skipped.append(SkippedPair(pair_id=pair.id, reason="no ground truth in index"))
            continue
        ticket = normalize(cache.raw_ticket(pair_set, pair, project_root), settings)
        result = retrieve(ticket, index, settings, client if use_llm else None)
        report.pairs.append(_score(pair, unit, present, truth, result))

    if report.pairs:
        report.mean_recall = round(sum(p.recall for p in report.pairs) / len(report.pairs), 4)
        report.mean_reciprocal_rank = round(
            sum(p.reciprocal_rank for p in report.pairs) / len(report.pairs), 4
        )
    return report


def _ground_truth(pair_set: PairSet, pair: EvalPair, cache: EvalCache) -> tuple[list[str], str]:
    if pair_set.ground_truth == "fix_pr_files":
        return [f for f in cache.fix_pr_files(pair) if f.endswith(".py")], "file"
    return [manifest_test_to_chunk_id(t) for t in pair.tests], "test"


def _score(
    pair: EvalPair, unit: str, present: list[str], truth: list[str], result: RetrievalResult
) -> PairResult:
    retrieved: list[str] = []
    for hit in result.hits:
        key = hit.file_path if unit == "file" else hit.chunk_id
        if key not in retrieved:
            retrieved.append(key)
    found = [t for t in present if t in retrieved]
    first = next((rank for rank, key in enumerate(retrieved, 1) if key in present), None)
    return PairResult(
        pair_id=pair.id,
        ticket=pair.ticket,
        unit=unit,
        ground_truth=present,
        not_in_index=[t for t in truth if t not in present],
        retrieved=retrieved,
        found=found,
        recall=round(len(found) / len(present), 4),
        reciprocal_rank=round(1 / first, 4) if first else 0.0,
        llm_calls=result.llm_calls,
        followup_rounds=result.followup_rounds,
    )


def render_markdown(report: RetrievalReport) -> str:
    def fmt(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.3f}"

    lines = [
        f"# Retrieval eval: {report.set_name}",
        "",
        f"- k = {report.k}, LLM steps: {'on' if report.use_llm else 'off (deterministic)'}",
        f"- Pairs evaluated: {len(report.pairs)}, skipped: {len(report.skipped)}",
        f"- **Mean recall@{report.k}: {fmt(report.mean_recall)}**",
        f"- Mean reciprocal rank: {fmt(report.mean_reciprocal_rank)}",
        f"- Created: {report.created_at:%Y-%m-%d %H:%M UTC}",
        "",
        "| Pair | Unit | Ground truth | Found | Recall | RR |",
        "|---|---|---|---|---|---|",
    ]
    for p in report.pairs:
        lines.append(
            f"| {p.pair_id} | {p.unit} | {len(p.ground_truth)} | "
            f"{', '.join(p.found) or '-'} | {p.recall:.2f} | {p.reciprocal_rank:.2f} |"
        )
    if report.skipped:
        lines += ["", "Skipped:", *(f"- {s.pair_id}: {s.reason}" for s in report.skipped)]
    return "\n".join(lines) + "\n"
