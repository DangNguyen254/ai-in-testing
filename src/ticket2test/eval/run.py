"""Run the eval harness over pair sets: retrieval (repeated), generation, mined-pair checks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ticket2test.config import Settings
from ticket2test.eval.generation import evaluate_generation
from ticket2test.eval.pairs import EvalCache, PairSet, load_pair_set
from ticket2test.eval.report import EvalRunReport, MinedCheck, PairSource
from ticket2test.eval.retrieval import evaluate_retrieval
from ticket2test.llm.base import LLMClient
from ticket2test.llm.factory import model_name

_KIND = {"fix_pr_files": "fix PR files", "tests": "linked tests"}


def load_pair_sets(path: Path) -> list[PairSet]:
    """A pair-set JSON file, or every ``*.json`` pair set in a folder (sorted)."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    return [load_pair_set(f) for f in files]


def run_eval(
    pair_sets: list[PairSet],
    project_root: Path,
    settings: Settings,
    client: LLMClient | None,
    stage: str = "retrieval",
    runs: int = 1,
    k: int | None = None,
    leave_one_out: bool = True,
    collect: bool = True,
    judge: bool = False,
    reuse_drafts: bool = True,
    keep_dir: Path | None = None,
) -> EvalRunReport:
    if stage not in ("retrieval", "generation", "all"):
        raise ValueError(f"unknown stage {stage!r} (retrieval, generation, all)")
    runs = max(1, runs)
    cache = EvalCache(settings)
    report = EvalRunReport(created_at=datetime.now(UTC), config=_snapshot(settings, client))
    for pair_set in pair_sets:
        mined = any(p.source and p.source.startswith("mined") for p in pair_set.pairs)
        kind = "mined from git history" if mined else _KIND[pair_set.ground_truth]
        report.sources.append(
            PairSource(set_name=pair_set.name, pairs=len(pair_set.pairs), kind=kind)
        )
    report.unique_pairs = len(
        {
            (p.ticket, p.fix_pr if s.ground_truth == "fix_pr_files" else tuple(sorted(p.tests)))
            for s in pair_sets
            for p in s.pairs
        }
    )
    report.mined = _mined_checks(pair_sets)

    if stage in ("retrieval", "all"):
        for pair_set in pair_sets:
            report.retrieval[pair_set.name] = [
                evaluate_retrieval(pair_set, project_root, settings, client, cache, k)
                for _ in range(runs)
            ]
    if stage in ("generation", "all"):
        targets = [s for s in pair_sets if s.generation]
        if not targets:
            raise ValueError('no pair set is marked for generation ("generation": true)')
        if client is None:
            raise ValueError("the generation stage needs the LLM (drop --no-llm)")
        report.generation = evaluate_generation(
            targets[0],
            project_root,
            settings,
            client,
            cache,
            leave_one_out=leave_one_out,
            collect=collect,
            judge=judge,
            reuse_drafts=reuse_drafts,
            keep_dir=keep_dir,
        )
    return report


def _mined_checks(pair_sets: list[PairSet]) -> list[MinedCheck]:
    """Mined pairs vs. the manually linked tests of the same ticket in the other sets."""
    linked: dict[str, set[str]] = {}
    for s in pair_sets:
        for p in s.pairs:
            if not (p.source or "").startswith("mined"):
                linked.setdefault(p.ticket, set()).update(p.tests)
    checks = []
    for s in pair_sets:
        for p in s.pairs:
            if (p.source or "").startswith("mined"):
                manual = linked.get(p.ticket)
                for test in p.tests:
                    checks.append(
                        MinedCheck(
                            ticket=p.ticket,
                            test=test,
                            source=p.source or "",
                            agrees=None if manual is None else test in manual,
                        )
                    )
    return checks


def _snapshot(settings: Settings, client: LLMClient | None) -> dict[str, Any]:
    return {
        "llm": "off" if client is None else settings.llm.provider,
        "models": {
            step: model_name(settings, step)
            for step in ("draft", "query_rewrite", "retrieval_followup", "generate")
        },
        "prompts": {
            "draft": settings.draft.prompt_version,
            "query_rewrite": settings.retrieval.query_rewrite_prompt,
            "generate": settings.generate.prompt_version,
            "repair": settings.repair.prompt_version,
        },
        "retrieval.top_k": settings.retrieval.top_k,
        "retrieval.max_followup_rounds": settings.retrieval.max_followup_rounds,
        "context.max_tokens": settings.context.max_tokens,
        "repair.max_attempts": settings.repair.max_attempts,
        "sandbox": f"{settings.sandbox.runtime} {settings.sandbox.image}",
    }
