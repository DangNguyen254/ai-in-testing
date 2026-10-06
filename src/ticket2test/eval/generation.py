"""Generation eval: ticket -> draft -> retrieval -> generate + repair -> validate -> collect.

For pair sets whose ground truth is the ticket's linked tests (the stand-in). Measured per
ticket: whether drafting worked, the validator result on the first attempt and after repair,
invented names on the first attempt (``names`` / ``imports`` errors), repair rounds, whether the
module collects in the sandbox, LLM calls, and time.

Leave-one-out (default): the ticket's own linked tests are removed from the index before
retrieval and generation, so the generator can't copy the answer.

Drafts can be reused from a cache (``<cache_dir>/eval/drafts``, keyed by ticket content, draft
prompt version, and model) to save LLM calls on repeated runs; each result says whether its
draft came from the cache.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import Settings
from ticket2test.draft import generate_drafts
from ticket2test.eval.judge import JudgeVerdict, judge_draft
from ticket2test.eval.pairs import EvalCache, EvalPair, PairSet
from ticket2test.eval.retrieval import manifest_test_to_chunk_id
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm.base import LLMClient, LLMError
from ticket2test.llm.factory import model_name
from ticket2test.models.draft import DraftResult
from ticket2test.models.ticket import Ticket
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve
from ticket2test.sandbox.runner import SandboxError, collect_generated
from ticket2test.style import format_entries
from ticket2test.validate.repair import generate_with_repair

_INVENTED = ("[names]", "[imports]")


class GenerationPairResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str
    ticket: str
    status: str  # "generated", "insufficient_info", "failed"
    error: str = ""
    draft_cached: bool = False
    test_kind: str | None = None
    file_name: str | None = None
    test_ids: list[str] = Field(default_factory=list)
    template: str | None = None
    leave_one_out_ok: bool | None = None  # the linked test stayed out of the context
    first_errors: list[str] = Field(default_factory=list)  # validator errors, first attempt
    invented_names: int = 0  # names / imports errors on the first attempt
    final_ok: bool = False
    final_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    repairs: int = 0
    collect_ok: bool | None = None  # None: not run
    collect_note: str = ""
    llm_calls: int = 0
    seconds: float = 0.0
    judge: JudgeVerdict | None = None


class GenerationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_name: str
    created_at: datetime
    leave_one_out: bool
    collect: bool
    judge: bool
    models: dict[str, str] = Field(default_factory=dict)
    pairs: list[GenerationPairResult] = Field(default_factory=list)
    llm_calls: int = 0
    elapsed_seconds: float = 0.0

    def _rate(self, values: list[bool]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    @property
    def generated(self) -> list[GenerationPairResult]:
        return [p for p in self.pairs if p.status == "generated"]

    def metrics(self) -> dict[str, Any]:
        gen = self.generated
        collected = [p.collect_ok for p in gen if p.collect_ok is not None]
        return {
            "pairs": len(self.pairs),
            "generated": len(gen),
            "insufficient_info": sum(p.status == "insufficient_info" for p in self.pairs),
            "failed": sum(p.status == "failed" for p in self.pairs),
            "first_attempt_pass_rate": self._rate([not p.first_errors for p in gen]),
            "final_pass_rate": self._rate([p.final_ok for p in gen]),
            "invented_name_rate": self._rate([p.invented_names > 0 for p in gen]),
            "invented_names_total": sum(p.invented_names for p in gen),
            "collect_pass_rate": self._rate(collected),
            "collect_runs": len(collected),
            "mean_repairs": round(sum(p.repairs for p in gen) / len(gen), 2) if gen else None,
            "warnings_per_test": round(sum(len(p.warnings) for p in gen) / len(gen), 2)
            if gen
            else None,
            "leave_one_out_violations": sum(p.leave_one_out_ok is False for p in gen),
        }


def index_without(index: IndexData, chunk_ids: set[str]) -> IndexData:
    """A copy of the index without these chunks (for leave-one-out)."""
    return index.model_copy(
        update={
            "chunks": [c for c in index.chunks if c.id not in chunk_ids],
            "tokens": {k: v for k, v in index.tokens.items() if k not in chunk_ids},
        }
    )


def evaluate_generation(
    pair_set: PairSet,
    project_root: Path,
    settings: Settings,
    client: LLMClient,
    cache: EvalCache | None = None,
    leave_one_out: bool = True,
    collect: bool = True,
    judge: bool = False,
    reuse_drafts: bool = True,
    keep_dir: Path | None = None,
) -> GenerationReport:
    """Run the generation pipeline for each pair. ``keep_dir``: write each generated pair."""
    if pair_set.ground_truth != "tests":
        raise ValueError(f"{pair_set.name}: generation needs a pair set with linked tests")
    repo = project_root / pair_set.repo_path
    index, _, _ = update_index(repo, settings)
    cache = cache or EvalCache(settings)
    conventions = (
        (project_root / pair_set.conventions_doc).read_text(encoding="utf-8")
        if pair_set.conventions_doc
        else None
    )
    report = GenerationReport(
        set_name=pair_set.name,
        created_at=datetime.now(UTC),
        leave_one_out=leave_one_out,
        collect=collect,
        judge=judge,
        models={
            step: model_name(settings, step) for step in ("draft", "query_rewrite", "generate")
        },
    )
    started = time.monotonic()
    for pair in pair_set.pairs:
        report.pairs.append(
            _one(
                pair, pair_set, project_root, repo, index, settings, client, cache,
                conventions, leave_one_out, collect, judge, reuse_drafts, keep_dir,
            )
        )  # fmt: skip
    report.llm_calls = sum(p.llm_calls for p in report.pairs)
    report.elapsed_seconds = round(time.monotonic() - started, 1)
    return report


def _one(
    pair: EvalPair,
    pair_set: PairSet,
    project_root: Path,
    repo: Path,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    cache: EvalCache,
    conventions: str | None,
    leave_one_out: bool,
    collect: bool,
    judge: bool,
    reuse_drafts: bool,
    keep_dir: Path | None,
) -> GenerationPairResult:
    started = time.monotonic()
    result = GenerationPairResult(pair_id=pair.id, ticket=pair.ticket, status="failed")
    linked = {manifest_test_to_chunk_id(t) for t in pair.tests}
    used_index = index_without(index, linked) if leave_one_out else index
    try:
        ticket = normalize(cache.raw_ticket(pair_set, pair, project_root), settings)
        drafts, cached, calls = _drafts(ticket, client, settings, cache, reuse_drafts)
        result.draft_cached, result.llm_calls = cached, calls
        if judge:
            verdict, judge_calls = judge_draft(ticket, drafts, client, settings)
            result.judge, result.llm_calls = verdict, result.llm_calls + judge_calls
        if drafts.status != "ok":
            result.status = "insufficient_info"
            return _finish(result, started)
        primary = next(d for d in drafts.drafts if d.kind == "primary")
        result.test_kind = primary.test_kind
        retrieval = retrieve(ticket, used_index, settings, client, primary)
        result.llm_calls += retrieval.llm_calls
        repaired = generate_with_repair(
            primary,
            retrieval,
            used_index,
            settings,
            client,
            provider=settings.llm.provider,
            model=model_name(settings, "generate"),
            conventions=conventions,
        )
    except LLMError as exc:
        result.error = str(exc)[:500]
        return _finish(result, started)

    generated, final = repaired.generated, repaired.report
    result.status = "generated"
    result.llm_calls += repaired.llm_calls
    result.file_name, result.test_ids = generated.file_name, generated.test_ids
    ref = generated.template_entry_ref
    result.template = ref.entry_key if ref else None
    result.leave_one_out_ok = not (
        linked & set(generated.retrieved_chunk_ids) or (ref and ref.chunk_id in linked)
    )
    result.first_errors = final.history[0] if final.history else [f.render() for f in final.errors]
    result.invented_names = sum(e.startswith(_INVENTED) for e in result.first_errors)
    result.final_ok = final.ok
    result.final_errors = [f.render() for f in final.errors]
    result.warnings = [f.render() for f in final.warnings]
    result.repairs = final.repairs
    if collect:
        try:
            collected = collect_generated(generated, repo, settings)
        except SandboxError as exc:
            result.collect_note = f"not run: {exc}"
        else:
            result.collect_ok = collected.ok
            if not collected.ok:
                result.collect_note = (
                    "timed out" if collected.timed_out else collected.output_tail[-400:]
                )
            generated = generated.model_copy(
                update={"collect_report": collected.model_dump(mode="json")}
            )
    if keep_dir is not None:
        _keep(keep_dir / pair.id, generated, settings)
    return _finish(result, started)


def _drafts(
    ticket: Ticket, client: LLMClient, settings: Settings, cache: EvalCache, reuse: bool
) -> tuple[DraftResult, bool, int]:
    model = model_name(settings, "draft")
    key = hashlib.sha256(
        f"{ticket.model_dump_json()}|{settings.draft.prompt_version}|{model}".encode()
    ).hexdigest()[:24]
    path = cache.root / "drafts" / f"{key}.json"
    if reuse and path.is_file():
        return DraftResult.model_validate_json(path.read_text(encoding="utf-8")), True, 0
    drafts = generate_drafts(ticket, client, settings, provider=settings.llm.provider, model=model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(drafts.model_dump_json(indent=2), encoding="utf-8")
    return drafts, False, drafts.attempts


def _keep(folder: Path, generated: Any, settings: Settings) -> None:
    (folder / Path(generated.file_name).parent).mkdir(parents=True, exist_ok=True)
    (folder / generated.file_name).write_text(generated.code, encoding="utf-8", newline="\n")
    data = format_entries(
        generated.data_entries, settings.data, settings.style.json_files, generated.data_format
    )
    (folder / generated.data_file_name).write_text(data, encoding="utf-8", newline="\n")
    (folder / "generated.json").write_text(generated.model_dump_json(indent=2), encoding="utf-8")


def _finish(result: GenerationPairResult, started: float) -> GenerationPairResult:
    result.seconds = round(time.monotonic() - started, 1)
    return result
