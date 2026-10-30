"""DraftResult -> Markdown for human review (written for non-engineers too)."""

from __future__ import annotations

from ticket2test.models.draft import (
    UNKNOWN,
    DraftResult,
    DraftSkeleton,
    DraftSupport,
    TestCaseDraft,
)
from ticket2test.models.ticket import Ticket

_MISSING_LABELS = {
    "steps_to_reproduce": "Steps to reproduce the problem",
    "expected_behavior": "What should happen instead (expected behavior)",
}
_TEST_KIND_LABELS = {"ui": "User interface", "api": "API", "hybrid": "User interface + API"}
_DEPLOYMENT_LABELS = {
    "cloud": "Cloud only",
    "on_prem": "On-premises only",
    "both": "All deployments",
}


def render_markdown(result: DraftResult, ticket: Ticket) -> str:
    lines = [f"# Test drafts for {ticket.id}: {ticket.title}", ""]
    if ticket.source.url:
        lines += [f"Ticket: {ticket.source.url}", ""]

    if result.status == "insufficient_info":
        lines += ["## Needs more information", "", "No test can be drafted yet. Missing:", ""]
        lines += [f"- {_MISSING_LABELS.get(item, item)}" for item in result.missing_info]
        if result.reason:
            lines += ["", f"Why: {result.reason}"]
        lines += [""]
        lines += _render_skeleton(result.skeleton) if result.skeleton else []
        lines += [_footer(result)]
        return "\n".join(lines) + "\n"

    if result.reason:
        lines += [f"Basis: {result.reason}", ""]
    for number, draft in enumerate(result.drafts, start=1):
        lines += _render_draft(number, draft)
    lines += _render_skeleton(result.skeleton) if result.skeleton else []
    lines.append(_footer(result))
    return "\n".join(lines) + "\n"


def _render_draft(number: int, draft: TestCaseDraft) -> list[str]:
    kind = "Main test" if draft.kind == "primary" else "Edge case"
    component = draft.markers.component
    if component == UNKNOWN:
        component = "unknown (could not tell from the ticket)"
    suite = draft.markers.suite if draft.markers.suite != UNKNOWN else "unknown"
    lines = [
        f"## {number}. {kind}: {draft.intent}",
        "",
        "| | |",
        "|---|---|",
        f"| Priority | {draft.markers.priority} |",
        f"| Component | {component} |",
        f"| Suite | {suite} |",
        f"| Test type | {_TEST_KIND_LABELS[draft.test_kind]} |",
        f"| Runs on | {_DEPLOYMENT_LABELS[draft.deployment_type]} |",
        "",
    ]
    if draft.support is not None:
        lines += _render_support(draft.support)
    if draft.preconditions:
        lines += ["**Before you start**", ""]
        lines += [f"- {item}" for item in draft.preconditions]
        lines.append("")
    lines += ["**Steps**", ""]
    lines += [f"{i}. {_one_line(step)}" for i, step in enumerate(draft.steps, start=1)]
    lines += ["", f"**Expected result:** {draft.expected_outcome}", ""]
    if draft.variants:
        lines += ["**Variations to check**", "", "| Case | Inputs | Expected |", "|---|---|---|"]
        for variant in draft.variants:
            inputs = ", ".join(f"{i.name} = {i.value}" for i in variant.inputs) or "-"
            lines.append(f"| {_cell(variant.name)} | {_cell(inputs)} | {_cell(variant.expected)} |")
        lines.append("")
    lines += [f"<sub>Draft ID: {draft.id}</sub>", ""]
    return lines


def _render_support(support: DraftSupport) -> list[str]:
    """What the ticket backs up, checked in code (not a model's score)."""

    def mark(ok: bool) -> str:
        return "yes" if ok else "**no**"

    numbers = f"**{', '.join(support.invented_numbers)}**" if support.invented_numbers else "none"
    added = ", ".join(support.ungrounded_words) or "none"
    variants = (
        f"**{', '.join(support.ungrounded_variants)}**" if support.ungrounded_variants else "none"
    )
    return [
        "**How well the ticket supports this draft** (checked in code)",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Ticket has explicit steps to reproduce | {mark(support.explicit_steps)} |",
        f"| Ticket has an explicit expected result | {mark(support.explicit_expected)} |",
        f"| Ticket has an explicit actual result | {mark(support.explicit_actual)} |",
        f"| Component named in the ticket | {mark(support.component_from_ticket)} |",
        f"| Numbers not in the ticket | {numbers} |",
        f"| Draft words found in the ticket | {round(support.grounding * 100)}% |",
        f"| Draft words not in the ticket | {_cell(added)} |",
        f"| Variants whose values the ticket doesn't name (remove unless meant) | "
        f"{_cell(variants)} |",
        "",
    ]


def _render_skeleton(skeleton: DraftSkeleton) -> list[str]:
    """The partial draft: what the ticket supports, with each unknown as a question."""
    kind = _TEST_KIND_LABELS.get(skeleton.test_kind, "unknown (the ticket doesn't say)")
    lines = [
        "## Partial draft (for discussion, not generated)",
        "",
        "What the ticket supports so far. Each [Q] marks something only the reporter can answer;",
        "no test is written until they are answered.",
        "",
        f"**Intent:** {skeleton.intent}",
        "",
        f"**Test type:** {kind}",
        "",
    ]
    if skeleton.preconditions:
        lines += ["**Before you start**", ""]
        lines += [f"- {item}" for item in skeleton.preconditions]
        lines.append("")
    lines += ["**Steps**", ""]
    lines += [f"{i}. {_one_line(step)}" for i, step in enumerate(skeleton.steps, start=1)]
    lines += ["", f"**Expected result:** {skeleton.expected_outcome}", ""]
    lines += [
        "**Questions for the reporter**",
        "",
        "| | Question | Why it matters |",
        "|---|---|---|",
    ]
    lines += [f"| {q.id} | {_cell(q.question)} | {_cell(q.why)} |" for q in skeleton.open_questions]
    lines.append("")
    if skeleton.notes:
        lines += [f"Note: {skeleton.notes}", ""]
    return lines


def _footer(result: DraftResult) -> str:
    return (
        f"<sub>Generated by {result.provider} ({result.model}), prompt {result.prompt_version}, "
        f"{result.attempts} LLM call(s), {result.redactions} secret(s) redacted.</sub>"
    )


def _one_line(text: str) -> str:
    # Multi-line steps (e.g. code) stay readable inside a numbered list item.
    return text if "\n" not in text else text.replace("\n", "\n   ")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
