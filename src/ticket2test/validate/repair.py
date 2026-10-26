"""Generate a test, validate it, and repair it from validator errors (capped).

The repair continues the generation conversation: the previous reply goes back as the
assistant's turn, followed by the validator errors (prompt ``repair_v1``). Only ``error``
findings trigger a repair; warnings are listed for the model but never block. The loop runs at
most ``repair.max_attempts`` rounds, then returns the last version with its report.
"""

from __future__ import annotations

from dataclasses import dataclass

from ticket2test.config import Settings
from ticket2test.generate.generator import (
    GenerationSetup,
    assemble,
    first_party,
    prepare_generation,
)
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient, Message
from ticket2test.llm.masking import masker_of
from ticket2test.llm.structured import StructuredOutputError, complete_structured
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.gaps import MissingPiece
from ticket2test.models.generated import GeneratedTest, GenerationResponse
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.prompts import PromptTemplate, load_prompt
from ticket2test.security import scrub_text
from ticket2test.style import format_entries
from ticket2test.validate.report import ValidationReport
from ticket2test.validate.validator import module_imports, validate_generated


@dataclass(frozen=True)
class RepairResult:
    generated: GeneratedTest  # with validation_report filled in
    report: ValidationReport
    llm_calls: int  # generation + repairs, retries included
    # Missing-piece candidates from every attempt: repair may drop a call to a member the suite
    # lacks to make the validators pass, which hides the gap from the final code.
    attempt_pieces: tuple[MissingPiece, ...] = ()


def validate_test(
    generated: GeneratedTest, setup: GenerationSetup, settings: Settings
) -> ValidationReport:
    data_text = format_entries(
        generated.data_entries, settings.data, settings.style.json_files, generated.data_format
    )
    return validate_generated(
        generated,
        setup.index.catalog,
        settings,
        first_party(setup.index, settings),
        setup.draft,
        data_text,
        module_imports(setup.index),
        setup.index,
    )


def generate_with_repair(
    draft: TestCaseDraft,
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    provider: str,
    model: str,
    conventions: str | None = None,
) -> RepairResult:
    setup = prepare_generation(draft, retrieval, index, settings, conventions)
    max_retries = settings.llm.max_retries_on_bad_json
    result = complete_structured(
        client,
        setup.request,
        GenerationResponse,
        max_retries=max_retries,
        context=setup.validation_context,
    )
    calls = result.attempts
    generated = assemble(setup, result.value, calls, provider, model, masker_of(client))
    report = validate_test(generated, setup, settings)
    pieces = _pieces(generated, index, settings, {})

    prompt = load_prompt(settings.repair.prompt_version, settings.paths.prompts_dir)
    messages = list(setup.request.messages)
    last_reply = result.response.text
    history: list[list[str]] = []
    while not report.ok and len(history) < settings.repair.max_attempts:
        history.append([f.render() for f in report.errors])
        messages += [
            Message(role="assistant", content=last_reply),
            Message(role="user", content=_repair_turn(prompt, report)),
        ]
        request = setup.request.model_copy(update={"messages": tuple(messages)})
        try:
            result = complete_structured(
                client,
                request,
                GenerationResponse,
                max_retries=max_retries,
                context=setup.validation_context,
            )
        except StructuredOutputError as exc:
            calls += exc.attempts
            break  # keep the last valid version and its report
        calls += result.attempts
        last_reply = result.response.text
        generated = assemble(setup, result.value, calls, provider, model, masker_of(client))
        report = validate_test(generated, setup, settings)
        pieces = _pieces(generated, index, settings, pieces)

    report.repairs = len(history)
    report.history = history
    final = generated.model_copy(
        update={"attempts": calls, "validation_report": report.model_dump(mode="json")}
    )
    return RepairResult(
        generated=final, report=report, llm_calls=calls, attempt_pieces=tuple(pieces.values())
    )


def _pieces(
    generated: GeneratedTest,
    index: IndexData,
    settings: Settings,
    found: dict[tuple[str, str], MissingPiece],
) -> dict[tuple[str, str], MissingPiece]:
    """Add this attempt's missing-piece candidates (first sighting wins)."""
    from ticket2test.gaps.collect import from_generated

    merged = dict(found)
    for piece in from_generated(generated, index, settings):
        merged.setdefault((piece.owner, piece.name), piece)
    return merged


def _repair_turn(prompt: PromptTemplate, report: ValidationReport) -> str:
    errors = "\n".join(f"- {f.render()}" for f in report.errors)
    warnings = "\n".join(f"- {f.render()}" for f in report.warnings) or "(none)"
    user = prompt.render_user(errors=scrub_text(errors), warnings=scrub_text(warnings))
    return f"{prompt.system}\n\n{user}"
