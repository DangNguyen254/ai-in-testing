"""Reuse first: decide how a draft becomes code, then build that, falling back when it can't.

1. the domain (a folder) and the decision (``generate/domain.py``, ``generate/reuse.py``);
   ``mode`` forces a kind instead (the CLI's ``--as``);
2. **covered**: nothing is generated; the existing test id is reported;
3. **variant**: a new case of the target test (``generate/patch.py``; code first, one small LLM
   call only when the draft's inputs don't say which values change);
4. **method**: the generator writes the test with the target class as template, and its methods
   are spliced into that class;
5. **module**: a new test file, scaffolded from the decision's class when it has one.

A variant that can't be patched falls back to a method in the same class, and a method that
can't be spliced is kept as the new module the generator already wrote (no second LLM call).
Each fallback is recorded in the output's reasons.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ticket2test.config import Settings
from ticket2test.gaps import check_pieces, from_generated, from_hints
from ticket2test.generate.domain import choose_domain
from ticket2test.generate.patch import (
    PatchError,
    method_patch,
    method_retrieval,
    validate_patch,
    variant_patch,
)
from ticket2test.generate.reuse import ReuseDecision, decide
from ticket2test.guides.context import area_guide_text
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.gaps import GapVerdict
from ticket2test.models.generated import GeneratedTest, ReuseKind
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.validate.repair import generate_with_repair
from ticket2test.validate.report import ValidationReport

Mode = Literal["auto", "variant", "method", "module"]


@dataclass
class ReuseOutcome:
    kind: ReuseKind  # what was produced (after fallbacks)
    decision: ReuseDecision  # what was decided
    generated: GeneratedTest | None = None  # None when covered
    report: ValidationReport | None = None
    notes: list[str] = field(default_factory=list)  # fallbacks taken
    guide: str = ""  # the area guide put into the context ("" when none), "(stale)" if so
    missing: list[GapVerdict] = field(default_factory=list)  # checked missing-piece candidates


def _generate_reusing(
    draft: TestCaseDraft,
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    provider: str,
    model: str,
    repo_root: Path,
    conventions: str | None = None,
    mode: Mode = "auto",
) -> ReuseOutcome:
    choice = choose_domain(retrieval, index, settings, None, draft)
    decision = decide(draft, retrieval, index, settings, choice)
    kind: ReuseKind = decision.kind if mode == "auto" else mode
    outcome = ReuseOutcome(kind=kind, decision=decision)
    if choice.domain is not None and settings.guides.use_in_generation:
        text, outcome.guide = area_guide_text(choice.domain.name, repo_root, index, settings)
        if text:
            conventions = f"{conventions}\n\n{text}" if conventions else text
    if mode != "auto" and mode != decision.kind:
        outcome.notes.append(f"--as {mode} (decided: {decision.kind})")
    if kind == "covered":
        return outcome

    if kind == "variant":
        target = _variant_target(decision)
        try:
            if target is None:
                raise PatchError("no parametrized test in the domain to add a case to")
            generated = variant_patch(
                draft,
                dataclasses.replace(decision, kind="variant", target=target),
                index,
                settings,
                repo_root,
                client,
                provider,
                model,
            )
            return _done(outcome, "variant", generated, index, settings, repo_root, draft)
        except PatchError as exc:
            outcome.notes.append(f"variant not possible: {exc}; trying a new method")
            kind = "method"

    if kind == "method":
        method = _method_target(decision)
        if method is None:
            outcome.notes.append("no class to add a method to; writing a new module")
        else:
            class_name, file_path = method
            chosen = dataclasses.replace(
                decision, kind="method", target=class_name, target_file=file_path
            )
            try:
                steered = method_retrieval(retrieval, index, class_name, file_path)
            except PatchError as exc:
                outcome.notes.append(f"method not possible: {exc}; writing a new module")
            else:
                repaired = generate_with_repair(
                    draft, steered, index, settings, client, provider, model, conventions
                )
                try:
                    generated = method_patch(repaired.generated, chosen, index, settings, repo_root)
                except PatchError as exc:
                    outcome.notes.append(
                        f"method not possible: {exc}; keeping the generated test as a new module"
                    )
                    return _module(outcome, repaired.generated, repaired.report)
                outcome = _done(outcome, "method", generated, index, settings, repo_root, draft)
                if outcome.report is not None:  # carry the generator's repair history over
                    outcome.report.repairs = repaired.report.repairs
                    outcome.report.history = repaired.report.history
                return outcome

    steered = retrieval
    if decision.kind == "module" and decision.target and decision.target_file:
        try:  # the scaffold and base class of the sibling the decision chose
            steered = method_retrieval(retrieval, index, decision.target, decision.target_file)
        except PatchError:
            steered = retrieval
    repaired = generate_with_repair(
        draft, steered, index, settings, client, provider, model, conventions
    )
    return _module(outcome, repaired.generated, repaired.report)


def generate_reusing(
    draft: TestCaseDraft,
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    provider: str,
    model: str,
    repo_root: Path,
    conventions: str | None = None,
    mode: Mode = "auto",
) -> ReuseOutcome:
    """Generate (or patch) the test, then check what it needed and the suite lacks: names the
    final test uses that don't exist, and the investigator's hints, each checked by code."""
    outcome = _generate_reusing(
        draft, retrieval, index, settings, client, provider, model, repo_root, conventions, mode
    )
    pieces = from_generated(outcome.generated, index, settings) if outcome.generated else []
    if retrieval.investigation is not None:
        pieces += from_hints(retrieval.investigation.missing)
    outcome.missing = check_pieces(pieces, index, settings)
    return outcome


def _variant_target(decision: ReuseDecision) -> str | None:
    if decision.kind == "variant":
        return decision.target
    return next((c.chunk_id for c in decision.candidates if c.param_ids), None)


def _method_target(decision: ReuseDecision) -> tuple[str, str] | None:
    if decision.kind == "method" and decision.target and decision.target_file:
        return decision.target, decision.target_file
    best = next((c for c in decision.candidates if c.class_name), None)
    return (best.class_name or "", best.file_path) if best else None


def _done(
    outcome: ReuseOutcome,
    kind: ReuseKind,
    generated: GeneratedTest,
    index: IndexData,
    settings: Settings,
    repo_root: Path,
    draft: TestCaseDraft,
) -> ReuseOutcome:
    report = validate_patch(generated, index, settings, repo_root, draft)
    outcome.kind, outcome.report = kind, report
    outcome.generated = generated.model_copy(
        update={
            "reuse_reasons": [*generated.reuse_reasons, *outcome.notes],
            "validation_report": report.model_dump(mode="json"),
        }
    )
    return outcome


def _module(
    outcome: ReuseOutcome, generated: GeneratedTest, report: ValidationReport
) -> ReuseOutcome:
    outcome.kind, outcome.report = "module", report
    outcome.generated = generated.model_copy(
        update={
            "reuse_kind": "module",
            "reuse_target": outcome.decision.target,
            "reuse_reasons": [*outcome.decision.reasons, *outcome.notes],
        }
    )
    return outcome
