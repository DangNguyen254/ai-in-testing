"""One eval run: retrieval (repeated runs), generation, judge; JSON + Markdown.

Measured metrics and LLM-judge results are kept apart: judge results are labelled
UNVALIDATED until they are compared with human labels on a sample.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.eval.generation import GenerationPairResult, GenerationReport
from ticket2test.eval.retrieval import RetrievalReport


class PairSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    set_name: str
    pairs: int
    kind: str  # "fix PR files", "linked tests", "mined from git history"


class MinedCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket: str
    test: str
    source: str
    agrees: bool | None  # matches the manually linked test (None: no manual link)


class EvalRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    sources: list[PairSource] = Field(default_factory=list)
    unique_pairs: int = 0  # distinct (ticket, ground truth) pairs over all sets
    mined: list[MinedCheck] = Field(default_factory=list)
    retrieval: dict[str, list[RetrievalReport]] = Field(default_factory=dict)  # set -> runs
    generation: GenerationReport | None = None
    config: dict[str, Any] = Field(default_factory=dict)  # snapshot of the settings used


def retrieval_summary(runs: list[RetrievalReport]) -> dict[str, Any]:
    recalls = [r.mean_recall for r in runs if r.mean_recall is not None]
    mrrs = [r.mean_reciprocal_rank for r in runs if r.mean_reciprocal_rank is not None]
    return {
        "runs": len(runs),
        "pairs": len(runs[0].pairs) if runs else 0,
        "use_llm": runs[0].use_llm if runs else False,
        "recall_mean": _mean(recalls),
        "recall_min": min(recalls) if recalls else None,
        "recall_max": max(recalls) if recalls else None,
        "mrr_mean": _mean(mrrs),
        "mrr_min": min(mrrs) if mrrs else None,
        "mrr_max": max(mrrs) if mrrs else None,
        "llm_calls": sum(r.llm_calls for r in runs),
        "seconds": round(sum(r.elapsed_seconds or 0 for r in runs), 1),
    }


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(report: EvalRunReport) -> str:
    lines = [f"# Eval report ({report.created_at:%Y-%m-%d %H:%M UTC})", ""]

    lines += ["## Pairs", "", "| Set | Kind | Pairs |", "|---|---|---|"]
    lines += [f"| {s.set_name} | {s.kind} | {s.pairs} |" for s in report.sources]
    lines += ["", f"Distinct ticket <-> ground-truth pairs: **{report.unique_pairs}**."]
    if report.mined:
        agree = sum(m.agrees is True for m in report.mined)
        lines += [
            "",
            f"Mined from git history: {len(report.mined)} pair(s); {agree} agree with the "
            "manually linked test.",
            "",
            "| Ticket | Test | Source | Agrees |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {m.ticket} | `{m.test}` | {m.source} | {_fmt(m.agrees)} |" for m in report.mined
        ]

    if report.retrieval:
        lines += [
            "",
            "## Measured: retrieval",
            "",
            "recall@k and MRR per set; with several runs, mean [min-max] (LLM steps are not "
            "deterministic; deterministic runs must be identical).",
            "",
            "| Set | LLM | Runs | Pairs | recall@k | MRR | LLM calls | Time (s) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for name, runs in report.retrieval.items():
            s = retrieval_summary(runs)
            lines.append(
                f"| {name} | {'on' if s['use_llm'] else 'off'} | {s['runs']} | {s['pairs']} | "
                f"{_fmt(s['recall_mean'])} [{_fmt(s['recall_min'])}-{_fmt(s['recall_max'])}] | "
                f"{_fmt(s['mrr_mean'])} [{_fmt(s['mrr_min'])}-{_fmt(s['mrr_max'])}] | "
                f"{s['llm_calls']} | {s['seconds']} |"
            )

    gen = report.generation
    if gen is not None:
        m = gen.metrics()
        lines += [
            "",
            "## Measured: generation",
            "",
            f"Set {gen.set_name}; leave-one-out: {'on' if gen.leave_one_out else 'off'}; "
            f"sandbox collect: {'on' if gen.collect else 'off'}; models: "
            + ", ".join(f"{k} = {v}" for k, v in gen.models.items())
            + ".",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Tickets | {m['pairs']} (generated {m['generated']}, covered {m['covered']}, "
            f"insufficient info {m['insufficient_info']}, failed {m['failed']}) |",
            "| Reuse (covered / variant / method / module) | "
            + " / ".join(
                str(m["reuse_kinds"][k]) for k in ("covered", "variant", "method", "module")
            )
            + f" ({m['fallbacks']} with a fallback) |",
            f"| Fixed in code instead of an LLM retry | {m['fixed_in_code']} |",
            f"| Validators pass, first attempt | {_fmt(m['first_attempt_pass_rate'])} |",
            f"| Validators pass, after repair | {_fmt(m['final_pass_rate'])} |",
            f"| Invented names, first attempt (share of tests) | {_fmt(m['invented_name_rate'])}"
            f" ({m['invented_names_total']} total) |",
            f"| `pytest --collect-only` pass rate (sandbox) | {_fmt(m['collect_pass_rate'])} "
            f"({m['collect_runs']} run) |",
            f"| Mean repair rounds | {_fmt(m['mean_repairs'])} |",
            f"| Reviewer warnings per test | {_fmt(m['warnings_per_test'])} |",
            f"| Leave-one-out violations | {m['leave_one_out_violations']} |",
            f"| LLM calls / time | {gen.llm_calls} / {gen.elapsed_seconds} s |",
            "",
            "| Ticket | Status | Kind | Reuse | First-attempt errors | Repairs | Final | Collect | "
            "Warnings | Calls | s |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for p in gen.pairs:
            lines.append(
                f"| {p.ticket} | {p.status}{' (cached draft)' if p.draft_cached else ''} | "
                f"{p.test_kind or '-'} | {_reuse(p)} | {len(p.first_errors)} | {p.repairs} | "
                f"{'ok' if p.final_ok else '-' if p.status != 'generated' else 'FAIL'} | "
                f"{_fmt(p.collect_ok)} | {len(p.warnings)} | {p.llm_calls} | {p.seconds} |"
            )
        problems = [p for p in gen.pairs if p.error or p.final_errors or p.collect_note]
        if problems:
            lines += ["", "Details:"]
            for p in problems:
                for text in [p.error, *p.final_errors, p.collect_note]:
                    if text:
                        lines.append(f"- {p.ticket}: {text.strip()[:300]}")

        judged = [p for p in gen.pairs if p.judge is not None]
        lines += ["", "## UNVALIDATED: LLM judge (draft matches ticket)", ""]
        if not judged:
            lines.append("Not run (enable with `--judge`; one extra LLM call per ticket).")
        else:
            lines += [
                "Not yet compared with human labels; treat as indicative only.",
                "",
                "| Ticket | Verdict | Score | Reason |",
                "|---|---|---|---|",
            ]
            for p in judged:
                assert p.judge is not None
                lines.append(
                    f"| {p.ticket} | {p.judge.verdict} | {p.judge.score:.2f} | "
                    f"{p.judge.reason.replace('|', '/')} |"
                )
            scores = [p.judge.score for p in judged if p.judge is not None]
            lines += ["", f"Mean judge score: {_fmt(_mean(scores))}."]

    snap = report.config
    if snap:
        lines += ["", "## Config snapshot", ""]
        lines += [f"- {k}: `{v}`" for k, v in snap.items()]
    return "\n".join(lines) + "\n"


def _reuse(p: GenerationPairResult) -> str:
    if p.reuse_kind is None:
        return "-"
    target = (p.reuse_target or "").rsplit("::", 1)[-1]
    shown = f"{p.reuse_kind} {target}".strip()
    return shown if p.decided in (None, p.reuse_kind) else f"{shown} (decided {p.decided})"
