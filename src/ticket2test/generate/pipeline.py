"""Reuse first: decide how a draft becomes code, then build that, falling back when it can't.

1. the domain (a folder) and the decision (``generate/domain.py``, ``generate/reuse.py``);
   ``mode`` forces a kind instead (the CLI's ``--as``);
2. **covered**: nothing is generated; the existing test id is reported (**out_of_scope**, a
   legacy area: nothing is generated either);
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
from ticket2test.models.gaps import GapVerdict, MissingPiece
from ticket2test.models.generated import GeneratedTest, ReuseKind
from ticket2test.models.proposal import Proposal
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.proposals import propose_gaps, use_kind
from ticket2test.proposals.apply import proposal_context, with_proposals
from ticket2test.validate.repair import generate_with_repair
from ticket2test.validate.report import ValidationReport
from ticket2test.validate.suite import file_findings

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
    attempt_pieces: list[MissingPiece] = field(default_factory=list)  # from every attempt
    proposals: list[Proposal] = field(default_factory=list)  # agent 2 patches (opt-in)
    uses_proposals: list[Proposal] = field(default_factory=list)  # the final test uses these
    first_generated: GeneratedTest | None = None  # the test before regenerating, if replaced


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
        files = [f for f in (decision.target_file, (decision.target or "").split("::")[0]) if f]
        text, outcome.guide = area_guide_text(
            choice.domain.name, repo_root, index, settings, files=files
        )
        if text:
            conventions = f"{conventions}\n\n{text}" if conventions else text
    if mode != "auto" and mode != decision.kind:
        outcome.notes.append(f"--as {mode} (decided: {decision.kind})")
    if kind in ("covered", "out_of_scope"):  # nothing to generate
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

                def in_class(
                    attempt: GeneratedTest,
                ) -> tuple[GeneratedTest, ValidationReport] | None:
                    """Each attempt judged where it will live: inside the existing class, whose
                    own helpers it may call (as a module, they would look missing)."""
                    try:
                        patched = method_patch(attempt, chosen, index, settings, repo_root)
                    except PatchError:
                        return None
                    return patched, validate_patch(patched, index, settings, repo_root, draft)

                repaired = generate_with_repair(
                    draft, steered, index, settings, client, provider, model, conventions,
                    check=in_class,
                )  # fmt: skip
                outcome.attempt_pieces = list(repaired.attempt_pieces)
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
    outcome.attempt_pieces = list(repaired.attempt_pieces)
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
    final test uses that don't exist, and the investigator's hints, each checked by code. With
    ``proposals.enabled``, each class-owned gap also gets a proposed member as a separate patch."""
    outcome = _generate_reusing(
        draft, retrieval, index, settings, client, provider, model, repo_root, conventions, mode
    )
    pieces = from_generated(outcome.generated, index, settings) if outcome.generated else []
    seen = {(p.owner, p.name) for p in pieces}
    pieces += [p for p in outcome.attempt_pieces if (p.owner, p.name) not in seen]
    if retrieval.investigation is not None:
        pieces += from_hints(retrieval.investigation.missing)
    outcome.missing = check_pieces(pieces, index, settings)
    gaps = [v for v in outcome.missing if v.status in ("missing", "close_match")]
    if gaps and settings.proposals.enabled:
        code = outcome.generated.code if outcome.generated else ""
        outcome.proposals = propose_gaps(gaps, code, index, settings, client, repo_root)
        accepted = [p for p in outcome.proposals if p.ok]
        if accepted and settings.proposals.regenerate and outcome.generated is not None:
            _regenerate(
                outcome, accepted, draft, retrieval, index, settings, client, provider, model,
                repo_root, conventions,
            )  # fmt: skip
    if gaps and outcome.generated is not None:  # put the warning where the reviewer looks
        used = {(p.owner_class, p.member): p for p in outcome.uses_proposals}
        notes = [
            _apply_note(used[key]) if key in used else _gap_note(v)
            for v in gaps
            for key in [(v.owner_class or "", v.piece.name)]
        ]
        checklist = [*outcome.generated.review_checklist, *notes]
        outcome.generated = outcome.generated.model_copy(update={"review_checklist": checklist})
    if outcome.generated is not None and outcome.decision.review_notes:
        checklist = [*outcome.generated.review_checklist, *outcome.decision.review_notes]
        outcome.generated = outcome.generated.model_copy(update={"review_checklist": checklist})
    if outcome.generated is not None:
        neighbours = _neighbour_notes(outcome.decision, index, settings, repo_root)
        if neighbours:
            checklist = [*outcome.generated.review_checklist, *neighbours]
            update = {"review_checklist": checklist}
            outcome.generated = outcome.generated.model_copy(update=update)
    return outcome


_DEVIATION_WORDS = {
    "raw_driver": "drive the browser directly",
    "page_locators": "use page locators directly",
    "constructed_pages": "build pages with constructors",
    "star_imports": "use a star import",
}


def _neighbour_notes(
    decision: ReuseDecision, index: IndexData, settings: Settings, repo_root: Path
) -> list[str]:
    """Correctness rules the new test follows but the tests next to it don't: a reviewer note
    per rule, since the usual way there may matter for how the page behaves."""
    path = decision.target_file
    if not path or not (repo_root / path).is_file():
        return []
    try:
        report = file_findings(repo_root, path, index, settings)
    except (OSError, ValueError):
        return []
    tests: dict[str, set[str]] = {}
    for finding in report.findings:
        if finding.severity == "error" and finding.check in settings.validation.deviation_checks:
            tests.setdefault(finding.check, set()).add(finding.test or "")
    notes = []
    for check, found in sorted(tests.items()):
        named = sorted(t for t in found if t)
        words = _DEVIATION_WORDS.get(check, f"break the {check} rule")
        who = f"{len(named)} test(s) in {path} {words}"
        if not named:  # a file-level finding (e.g. an import) has no test
            who = f"{path} breaks the {check} rule"
        notes.append(
            f"{who}; this test follows the rule instead. Confirm in a real run that it reaches "
            "the same state."
        )
    return notes


def _regenerate(
    outcome: ReuseOutcome,
    accepted: list[Proposal],
    draft: TestCaseDraft,
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    provider: str,
    model: str,
    repo_root: Path,
    conventions: str | None,
) -> None:
    """Generate again with the accepted members in the catalog and the context. The new test
    replaces the first only if it passes validation and uses at least one of them."""
    extra = proposal_context(accepted)
    second = _generate_reusing(
        draft,
        retrieval,
        with_proposals(index, accepted),
        settings,
        client,
        provider,
        model,
        repo_root,
        f"{conventions}\n\n{extra}" if conventions else extra,
        outcome.kind if outcome.kind in ("variant", "method", "module") else "auto",
    )
    generated, report = second.generated, second.report
    used = [p for p in accepted if generated and use_kind(generated.code, p.member)]
    if generated is None or report is None or not report.ok or not used:
        why = (
            "it failed validation"
            if report is not None and not report.ok
            else ("it didn't use them" if generated is not None else "nothing was generated")
        )
        outcome.notes.append(f"generated again with the proposed members; kept the first: {why}")
        return
    outcome.first_generated = outcome.generated
    outcome.generated, outcome.report, outcome.kind = generated, report, second.kind
    outcome.uses_proposals = used
    names = ", ".join(p.member for p in used)
    outcome.notes.append(f"generated again with the proposed members; the test uses {names}")


def _apply_note(proposal: Proposal) -> str:
    owner = proposal.owner_class.rsplit(".", 1)[-1]
    return (
        f"This test uses {owner}.{proposal.member}, which the suite doesn't have yet: it is "
        f"proposed in proposal_{proposal.member}.diff. Review and apply that patch first."
    )


def _gap_note(verdict: GapVerdict) -> str:
    piece = verdict.piece
    owner = (verdict.owner_class or piece.owner).rsplit(".", 1)[-1]
    where = f"{owner}.{piece.name}" if owner else piece.name
    close = f" (similar: {', '.join(verdict.close)})" if verdict.close else ""
    return (
        f"The ticket needs {where}, which the suite doesn't have{close}. This test may work "
        "around it, so it doesn't fully test the ticket until that exists."
    )


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
