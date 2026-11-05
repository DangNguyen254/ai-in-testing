"""The golden set: real tickets with the test a person wrote, run k times each and scored against
that test (docs/design-step-plan.md, Step 1).

Each run is the generation eval for one pair (leave-one-out, the pair's reviewed draft when it has
one), scored by ``eval.reference``. The report gives, per criterion, **pass@1** (the share of all
runs that pass) and **pass^k** (the share of tickets whose k runs all pass): one lucky run no
longer looks like a fix, and an old problem coming back shows as a low pass^k.

Written next to the report: ``c6.csv`` (a person's yes/no per run: do the checks cover the
expected outcome?), merged back with ``golden-report --c6``, and ``open-coding.md`` (one line
per run for the error analysis: the first failure, in a person's words).
"""

from __future__ import annotations

import csv
import gc
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import Settings
from ticket2test.eval.generation import (
    GenerationPairResult,
    _one,
    hidden_tests,
    loo_copy,
    loo_settings,
)
from ticket2test.eval.pairs import EvalCache, EvalPair, PairSet
from ticket2test.eval.reference import CRITERIA, ReferenceFacts, reference_facts, score
from ticket2test.eval.retrieval import manifest_test_to_chunk_id
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm.base import LLMClient
from ticket2test.llm.factory import model_name
from ticket2test.llm.meter import Usage, UsageMeter, usage_of
from ticket2test.validate.validator import clear_index_caches


class GoldenRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str
    run: int
    result: GenerationPairResult
    scores: dict[str, Any]
    c6: bool | None = None  # a person's answer, merged from c6.csv
    kept: str = ""  # where the run's output was written


class GoldenReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    set_name: str
    created_at: datetime
    repeat: int
    config: dict[str, Any] = Field(default_factory=dict)
    runs: list[GoldenRun] = Field(default_factory=list)
    llm_calls: int = 0
    usage: Usage | None = None
    elapsed_seconds: float = 0.0

    def summary(self) -> dict[str, dict[str, float | None]]:
        """Per criterion: pass@1 over all runs, pass^k over tickets (all runs pass)."""
        criteria = [*CRITERIA, "c6"]
        by_pair: dict[str, list[GoldenRun]] = {}
        for run in self.runs:
            by_pair.setdefault(run.pair_id, []).append(run)
        out: dict[str, dict[str, float | None]] = {}
        for name in criteria:
            values = [_value(r, name) for r in self.runs]
            known = [v for v in values if v is not None]
            pairs = [
                [_value(r, name) for r in runs]
                for runs in by_pair.values()
                if all(_value(r, name) is not None for r in runs)
            ]
            out[name] = {
                "pass@1": round(sum(known) / len(known), 3) if known else None,
                "pass^k": round(sum(all(p) for p in pairs) / len(pairs), 3) if pairs else None,
            }
        return out


def _value(run: GoldenRun, name: str) -> bool | None:
    if name == "c6":
        return run.c6
    if run.result.status != "generated":
        return False
    return bool(run.scores.get(name))


def run_golden(
    pair_set: PairSet,
    project_root: Path,
    settings: Settings,
    client: LLMClient,
    repeat: int,
    label: str,
    keep_dir: Path,
    collect: bool = False,
    progress: Callable[[str], None] | None = None,
) -> GoldenReport:
    """Two phases, so at most one index is in memory at a time (a large suite's index is over a
    gigabyte): first, with the full index, each pair's reference facts and leave-one-out copy;
    then, pair by pair, the copy's index and its runs."""
    say = progress or (lambda _: None)
    repeat = max(1, min(repeat, settings.eval.max_golden_repeat))
    repo = project_root / pair_set.repo_path
    say(f"indexing the suite: {repo}")
    index: IndexData | None = update_index(repo, settings)[0]
    assert index is not None
    prepared: list[tuple[EvalPair, ReferenceFacts | None, Path, set[str]]] = []
    for number, pair in enumerate(pair_set.pairs, start=1):
        linked = {manifest_test_to_chunk_id(t) for t in pair.tests} | hidden_tests(pair.hide, index)
        facts = reference_facts(pair.tests, index, settings, linked)
        copy = loo_copy(pair, repo, index, linked, settings, whole=collect)
        say(f"[{number}/{len(pair_set.pairs)}] {pair.id}: copy without {len(linked)} test(s) ready")
        prepared.append((pair, facts, copy, linked))
    index = None  # the full index isn't needed again: free it before the copies are indexed
    clear_index_caches()
    gc.collect()
    metered = UsageMeter(client)
    cache = EvalCache(settings)
    conventions = (
        (project_root / pair_set.conventions_doc).read_text(encoding="utf-8")
        if pair_set.conventions_doc
        else None
    )
    report = GoldenReport(
        label=label,
        set_name=pair_set.name,
        created_at=datetime.now(UTC),
        repeat=repeat,
        config=config_snapshot(settings),
    )
    started = time.monotonic()
    before = usage_of(metered)
    total = len(prepared) * repeat
    done = 0
    for pair, facts, copy, linked in prepared:
        say(f"{pair.id}: indexing its copy")
        used_index = update_index(copy, loo_settings(settings))[0]
        for run in range(1, repeat + 1):
            folder = keep_dir / pair.id / f"r{run}"
            capture: dict[str, Any] = {}
            run_started = time.monotonic()
            result = _one(
                pair, pair_set, project_root, copy, used_index, settings, metered, cache,
                conventions, True, collect, False, True, folder.parent, capture,
                prepared=(copy, used_index, linked),
            )  # fmt: skip
            done += 1
            say(
                f"run {done}/{total} {pair.id} r{run}: {result.status}, "
                f"{result.llm_calls} call(s), {time.monotonic() - run_started:.0f} s"
                + (f" ({result.error[:120]})" if result.error else "")
            )
            kept = keep_dir / pair.id / pair.id
            if kept.exists():  # _one writes <keep>/<pair id>: move it to the run's folder
                folder.parent.mkdir(parents=True, exist_ok=True)
                if folder.exists():
                    shutil.rmtree(folder)
                kept.rename(folder)
            scores = score(
                capture.get("generated"),
                facts,
                settings,
                result.warnings,
                result.final_ok,
                result.collect_ok,
                used_index,
            )
            report.runs.append(
                GoldenRun(
                    pair_id=pair.id,
                    run=run,
                    result=result,
                    scores=scores.as_dict(),
                    kept=str(folder) if folder.exists() else "",
                )
            )
        del used_index, capture  # one copy's index at a time
        clear_index_caches()
        gc.collect()
    report.llm_calls = sum(r.result.llm_calls for r in report.runs)
    after = usage_of(metered)
    if before is not None and after is not None:
        report.usage = after.minus(before)
    report.elapsed_seconds = round(time.monotonic() - started, 1)
    return report


def select_pairs(pair_set: PairSet, wanted: list[str] | None) -> PairSet:
    """The pair set with only the pairs named (ids, repeatable or comma-separated); all of
    them when none is named. An unknown id is an error, so a typo doesn't silently run less."""
    if not wanted:
        return pair_set
    ids = [i.strip() for raw in wanted for i in raw.split(",") if i.strip()]
    known = {p.id for p in pair_set.pairs}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f"no pair {', '.join(unknown)} in {pair_set.name} (has {len(known)})")
    keep = set(ids)
    return pair_set.model_copy(update={"pairs": [p for p in pair_set.pairs if p.id in keep]})


def rescore_golden(
    report: GoldenReport,
    pair_set: PairSet,
    project_root: Path,
    settings: Settings,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Score a finished run again from its kept outputs (after a scorer fix): no model calls.
    The reference facts come from the full index, each run's calls resolve against its pair's
    leave-one-out copy (left in the cache by the run, rebuilt if gone). The C6 answers stay.
    Returns how many runs were scored."""
    from ticket2test.models.generated import GeneratedTest

    say = progress or (lambda _: None)
    repo = project_root / pair_set.repo_path
    say(f"indexing the suite: {repo}")
    index: IndexData | None = update_index(repo, settings)[0]
    assert index is not None
    pairs = {p.id: p for p in pair_set.pairs}
    facts: dict[str, tuple[ReferenceFacts | None, Path]] = {}
    for pair_id in dict.fromkeys(r.pair_id for r in report.runs):
        pair = pairs.get(pair_id)
        if pair is None:
            continue
        linked = {manifest_test_to_chunk_id(t) for t in pair.tests} | hidden_tests(pair.hide, index)
        copy = settings.paths.cache_dir / "eval" / "loo" / pair.id
        if not copy.is_dir():
            copy = loo_copy(pair, repo, index, linked, settings)
        facts[pair_id] = (reference_facts(pair.tests, index, settings, linked), copy)
    index = None
    clear_index_caches()
    gc.collect()
    scored = 0
    for pair_id, (pair_facts, copy) in facts.items():
        say(f"{pair_id}: indexing its copy")
        used_index = update_index(copy, loo_settings(settings))[0]
        for run in report.runs:
            if run.pair_id != pair_id or not run.kept:
                continue
            path = Path(run.kept) / "generated.json"
            generated = (
                GeneratedTest.model_validate_json(path.read_text(encoding="utf-8"))
                if path.is_file()
                else None
            )
            result = run.result
            run.scores = score(
                generated,
                pair_facts,
                settings,
                result.warnings,
                result.final_ok,
                result.collect_ok,
                used_index,
            ).as_dict()
            scored += 1
        del used_index
        clear_index_caches()
        gc.collect()
    return scored


def config_snapshot(settings: Settings) -> dict[str, Any]:
    """The switches an ablation changes, so two reports can be compared."""
    g, k = settings.generate, settings.knowledge
    return {
        "models": {s: model_name(settings, s) for s in ("draft", "query_rewrite", "generate")},
        "prompts": {
            "draft": settings.draft.prompt_version,
            "generate": g.prompt_version,
            "repair": settings.repair.prompt_version,
        },
        "context.max_tokens": settings.context.max_tokens,
        "guides.use_in_generation": settings.guides.use_in_generation,
        "guides.framework": settings.guides.framework,
        "knowledge.use_in_draft": k.use_in_draft,
        "knowledge.use_in_generation": k.use_in_generation,
        "knowledge.glossary": str(k.glossary) if k.glossary else None,
        "generate.reuse.coverage_check": g.reuse.coverage_check,
        "generate.reuse.both_means_unspecified": g.reuse.both_means_unspecified,
        "generate.reuse.kind_fallback": g.reuse.kind_fallback,
        "generate.reuse.classes_from_domain": g.reuse.classes_from_domain,
        "generate.reuse.template_class_wins": g.reuse.template_class_wins,
        "generate.context_helpers": g.context_helpers,
        "generate.context_entry_list": g.context_entry_list,
        "generate.base_entry_from_class": g.base_entry_from_class,
        "repair.max_attempts": settings.repair.max_attempts,
        "repair.warning_checks": list(settings.repair.warning_checks),
        "proposals.enabled": settings.proposals.enabled,
    }


# --- files next to the report ----------------------------------------------------------------


def write_sheets(report: GoldenReport, folder: Path) -> list[Path]:
    """``c6.csv`` (a person's yes/no per run) and ``open-coding.md`` (the first failure per
    run, in a person's words), unless they exist already (they hold a person's answers)."""
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    sheet = folder / "c6.csv"
    if not sheet.exists():
        with sheet.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["pair_id", "run", "output", "checks_cover_expected_outcome (yes/no)"])
            for run in report.runs:
                if run.result.status == "generated":
                    writer.writerow([run.pair_id, run.run, run.kept, ""])
        written.append(sheet)
    coding = folder / "open-coding.md"
    if not coding.exists():
        lines = [
            f"# Open coding: {report.label}",
            "",
            "One line per run: the first thing that's wrong, in your own words (not a category).",
            "Group the lines into fewer than 10 failure modes afterwards and count them.",
            "",
        ]
        for run in report.runs:
            s = run.scores
            hints = []
            if s.get("missing_helpers"):
                hints.append(f"helpers not called: {len(s['missing_helpers'])}")
            if s.get("inlined"):
                hints.append(f"inlined: {len(s['inlined'])}")
            if s.get("missing_blocks"):
                hints.append(f"blocks missing: {len(s['missing_blocks'])}")
            hint = f" ({'; '.join(hints)})" if hints else ""
            lines += [
                f"- **{run.pair_id} r{run.run}** [{run.result.status}]{hint} `{run.kept}`",
                "  - first failure: ",
            ]
        coding.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(coding)
    return written


def merge_c6(report: GoldenReport, sheet: Path) -> int:
    """Answers from ``c6.csv`` into the report; returns how many were read."""
    answers: dict[tuple[str, int], bool] = {}
    with sheet.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("checks_cover_expected_outcome (yes/no)") or "").strip().lower()
            if raw in ("yes", "y", "no", "n"):
                answers[(row["pair_id"], int(row["run"]))] = raw.startswith("y")
    for run in report.runs:
        run.c6 = answers.get((run.pair_id, run.run), run.c6)
    return len(answers)


def render_report(report: GoldenReport) -> str:
    summary = report.summary()
    names = {
        "c1": "C1 placement (file and class)",
        "c2": "C2 helpers called, none inlined",
        "c3": "C3 data blocks present",
        "c4": "C4 no made-up values",
        "c5": "C5 number of cases",
        "c6": "C6 checks cover the outcome (person)",
        "c7": "C7 validators (and collect) pass",
        "c8": "C8 context held the helpers and blocks",
    }
    lines = [
        f"# Golden set: {report.label}",
        "",
        f"- Set `{report.set_name}`, {len({r.pair_id for r in report.runs})} tickets x "
        f"{report.repeat} runs, {report.created_at:%Y-%m-%d %H:%M} UTC",
        f"- LLM calls: {report.llm_calls}"
        + (f", ${report.usage.cost_usd:.2f}" if report.usage and report.usage.cost_usd else ""),
        "",
        "| Criterion | pass@1 | pass^k |",
        "|---|---|---|",
    ]
    for key in ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"]:
        row = summary[key]
        lines.append(f"| {names[key]} | {_fmt(row['pass@1'])} | {_fmt(row['pass^k'])} |")
    lines += [
        "",
        "Reading C8 with C2/C3: C8 fails -> retrieval missed it; C8 passes but C2/C3 fail -> "
        "the model had it and didn't use it.",
        "",
        "## Runs",
        "",
        "| Ticket | Run | Status | C1 | C2 (recall) | C3 (recall) | C4 | C5 | C6 | C7 "
        "| C8 (helpers/blocks) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in report.runs:
        if run.result.status != "generated":
            lines.append(f"| {run.pair_id} | {run.run} | {run.result.status} |" + " - |" * 8)
            continue
        s = run.scores
        m = {key: "yes" if s.get(key) else "**no**" for key in CRITERIA}
        c6 = "-" if run.c6 is None else ("yes" if run.c6 else "**no**")
        lines.append(
            f"| {run.pair_id} | {run.run} | generated | {m['c1']}"
            f"{' (' + s['c1_why'] + ')' if s.get('c1_why') else ''} | "
            f"{m['c2']} ({s.get('c2_recall', 0):.2f}) | {m['c3']} ({s.get('c3_recall', 0):.2f}) "
            f"| {m['c4']} | {m['c5']} | {c6} | {m['c7']} | "
            f"{m['c8']} ({s.get('c8_helpers', 0):.2f}/{s.get('c8_blocks', 0):.2f}) |"
        )
    lines += ["", "## Config", "", "```json", _json(report.config), "```", ""]
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _json(value: Any) -> str:
    import json

    return json.dumps(value, indent=2)
