"""Guides as Markdown: for the reviewer, for a run report, and for the generation context."""

from __future__ import annotations

from ticket2test.generate.context import estimate_tokens
from ticket2test.models.guide import AreaGuide, GuideOutput, GuideRef, GuideRun


def render_guide(g: AreaGuide) -> str:
    cost = f"${g.cost_usd:.4f}" if g.cost_usd is not None else "unknown"
    tokens = (
        f"{g.usage.input_tokens} in / {g.usage.output_tokens} out" if g.usage else "not metered"
    )
    lines = [
        f"# Area guide: {g.area}",
        "",
        f"Written by `{g.model}` (prompt `{g.prompt_version}`) on {g.built_at:%Y-%m-%d %H:%M UTC} "
        f"from area digest `{g.digest[:12]}`. Tokens: {tokens}; cost: {cost}.",
        "Names were checked against the index; see the end for what was removed.",
        "",
        _body(g.guide),
        "## Check",
        "",
        f"- Shown to the model: {', '.join(f'`{p}`' for p in g.input_pieces)}",
    ]
    lines += [f"- Removed: {r}" for r in g.removed] or ["- Removed: nothing"]
    if g.unverified:
        lines.append(
            "- Unverified mentions (not in the index; may be literal values): "
            + ", ".join(f"`{u}`" for u in g.unverified)
        )
    return "\n".join(lines) + "\n"


def guide_context(g: AreaGuide, max_tokens: int, chars_per_token: float) -> str:
    """The guide for the generation context, within ``max_tokens``: whole sections are dropped
    from the end (pitfalls are kept before examples), never cut mid-line."""
    out = g.guide
    sections = [
        ("Summary", [out.summary]),
        ("How to add a test here", [f"{i}. {s}" for i, s in enumerate(out.how_to_add, 1)]),
        ("Test classes", _refs(out.classes)),
        ("Page objects", _refs(out.page_objects)),
        ("Helpers", _refs(out.helpers)),
        ("Data entries", [f"- {d}" for d in out.data]),
        ("Pitfalls", [f"- {p}" for p in out.pitfalls]),
        ("Examples to copy", _refs(out.examples)),
    ]
    head = f"Area guide for `{g.area}` (written once by a stronger model; names checked):"
    text = head
    for title, rows in sections:
        if not rows or rows == [""]:
            continue
        block = f"\n\n#### {title}\n" + "\n".join(rows)
        if estimate_tokens(text + block, chars_per_token) > max_tokens:
            continue
        text += block
    return text


def render_run(run: GuideRun) -> str:
    estimated = sum(i.cost_estimate_usd or 0 for i in run.items if i.status != "up_to_date")
    lines = [
        f"# Area guides: {'estimate' if run.estimate_only else 'run'}",
        "",
        f"- Model `{run.model}`, prompt `{run.prompt_version}`",
        f"- Budget ${run.budget_usd:.2f} (ceiling ${run.ceiling_usd:.2f})"
        + ("" if run.prices_known else "; **no price configured for this model**"),
        f"- Worst case for the areas to build: ${estimated:.2f} (one call each; the budget is "
        "checked again before every call, retries included)",
        f"- Per call: estimated prompt + {run.overhead_tokens} overhead tokens in, "
        f"{run.output_allowance_tokens} tokens out (configured, raised by measured calls)",
    ]
    if not run.estimate_only:
        lines.append(f"- Spent: ${run.spent_usd:.4f}")
    if run.stopped:
        lines.append(f"- Stopped: {run.stopped}")
    lines += [
        "",
        "| Area | Tests | Status | Input tokens (est.) | Worst case $ | Actual $ | "
        "Tokens in / out | Removed | Unverified | s |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i in run.items:
        worst = "-" if i.cost_estimate_usd is None else f"{i.cost_estimate_usd:.4f}"
        actual = "-" if i.cost_usd is None else f"{i.cost_usd:.4f}"
        tokens = f"{i.usage.input_tokens} / {i.usage.output_tokens}" if i.usage else "-"
        lines.append(
            f"| {i.area} | {i.tests} | {i.status} | {i.input_tokens_estimate} | {worst} | "
            f"{actual} | {tokens} | {i.removed} | {i.unverified} | {i.seconds or '-'} |"
        )
    notes = [f"- {i.area}: {i.note}" for i in run.items if i.note]
    if notes:
        lines += ["", "Notes:", *notes]
    return "\n".join(lines) + "\n"


def _body(out: GuideOutput) -> str:
    parts = [
        "## Summary",
        "",
        out.summary,
        "",
        "## How to add a test here",
        "",
        *[f"{i}. {s}" for i, s in enumerate(out.how_to_add, 1)],
        "",
    ]
    for title, refs in (
        ("Test classes", out.classes),
        ("Page objects", out.page_objects),
        ("Helpers", out.helpers),
        ("Examples to copy", out.examples),
    ):
        parts += [f"## {title}", "", *(_refs(refs) or ["- none"]), ""]
    parts += ["## Data entries", "", *([f"- {d}" for d in out.data] or ["- none"]), ""]
    parts += ["## Pitfalls", "", *([f"- {p}" for p in out.pitfalls] or ["- none"]), ""]
    return "\n".join(parts)


def _refs(refs: list[GuideRef]) -> list[str]:
    return [f"- `{r.name}`: {r.use}" for r in refs]
