"""The planning step (bounded agent 5): before the test is written, the model looks members up
in the indexed suite and returns a plan, one row per draft line. It writes no code.

Two capped loops on one budget. **Turns**: the model asks for read-only lookups (the
investigator's tools) or returns the plan. **Rounds**: code checks the plan and sends back the
rows that fail (a member the class it leads to doesn't have, a call without a member, a draft
line no row covers). The first round may use the whole turn budget, later rounds a small one.
What still fails after the last round becomes a gap: a gap is a valid row, a guess is not.

A member the catalog can't type (a chain through a class outside the repo, a dynamic
attribute) is ``unknown``, never an error: the lookups read code the catalog can't resolve.
"""

from __future__ import annotations

import ast
from collections import Counter

from ticket2test.config import Settings
from ticket2test.generate.entries import function_of
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.chunk import Chunk
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import GeneratedTest
from ticket2test.models.plan import CheckedRow, Plan, PlannerStep, PlanRow, PlanStop, RowVerdict
from ticket2test.prompts import load_prompt
from ticket2test.retrieve.investigator import IndexTools, _Transcript
from ticket2test.retrieve.pipeline import Retriever
from ticket2test.security import scrub_text

_SENT_BACK: tuple[RowVerdict, ...] = ("missing", "no_member", "not_planned")


def draft_lines(draft: TestCaseDraft) -> list[tuple[str, str]]:
    """The draft as labelled lines: P1.. preconditions, S1.. steps, E the expected outcome."""
    lines = [(f"P{n}", text) for n, text in enumerate(draft.preconditions, 1)]
    lines += [(f"S{n}", text) for n, text in enumerate(draft.steps, 1)]
    if draft.expected_outcome.strip():
        lines.append(("E", draft.expected_outcome))
    return lines


def member_verdict(member: str, class_name: str, index: IndexData) -> RowVerdict:
    """Does the member exist, resolved from ``class_name`` the way a test's ``self`` is?"""
    written = member.strip().removeprefix("self.").removesuffix("()")
    if not written:
        return "no_member"
    catalog = index.catalog
    *steps, name = written.split(".")
    if not steps:
        owner = catalog.class_named(class_name)
    else:
        resolution = catalog.resolve_chain(class_name, [s.removesuffix("()") for s in steps])
        if resolution.status == "missing":
            return "missing"
        last = resolution.types[-1] if resolution.ok and resolution.types else None
        owner = catalog.classes.get(last) if last else None
    if owner is None:
        return "unknown"
    if catalog.member(owner.qualname, name) is not None:
        return "ok"
    return "unknown" if catalog.external_bases(owner.qualname) else "missing"


def check_rows(
    rows: list[PlanRow], lines: list[tuple[str, str]], class_name: str, index: IndexData
) -> list[CheckedRow]:
    """Every row with its verdict, rows for lines the draft doesn't have dropped, and a
    ``not_planned`` gap for every draft line without a row. In the draft's order."""
    labels = [label for label, _ in lines]
    checked: list[CheckedRow] = []
    for label in labels:
        mine = [r for r in rows if r.line.strip().upper() == label]
        for row in mine:
            verdict: RowVerdict = (
                member_verdict(row.member, class_name, index)
                if row.kind in ("call", "check")
                else "ok"
            )
            checked.append(
                CheckedRow(
                    line=label, kind=row.kind, member=row.member, note=row.note, verdict=verdict
                )
            )
        if not mine:
            checked.append(
                CheckedRow(line=label, kind="gap", member="", note="", verdict="not_planned")
            )
    return checked


def _feedback(failing: list[CheckedRow]) -> str:
    why = {
        "missing": "the class this leads to has no such member (open the class and look)",
        "no_member": "a call or check row needs a member",
        "not_planned": "no row covers this draft line",
    }
    return "\n".join(
        f"- {r.line}" + (f" `{r.member}`" if r.member else "") + f": {why[r.verdict]}"
        for r in failing
    )


def _render_rows(rows: list[PlanRow]) -> str:
    if not rows:
        return "(no rows yet)"
    return "\n".join(
        f"- {r.line} {r.kind}" + (f" `{r.member}`" if r.member else "") + f": {r.note}"
        for r in rows
    )


def make_plan(
    draft: TestCaseDraft,
    template: Chunk | None,
    class_name: str,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
) -> Plan:
    """``template``: the closest existing test, shown as a starting point (not a skeleton).
    ``class_name``: the class the new test goes into, or the one its new class is built like."""
    cfg = settings.generate.planner
    prompt = load_prompt(cfg.prompt, settings.paths.prompts_dir)
    tools = IndexTools(Retriever(index, settings), settings.retrieval.investigator)
    transcript = _Transcript(settings.retrieval.investigator.max_transcript_chars)
    lines = draft_lines(draft)
    seen: set[tuple[str, str]] = set()
    sent_back: Counter[str] = Counter()
    rows: list[PlanRow] = []
    checked: list[CheckedRow] = []
    feedback = "(none)"
    turns = rounds = llm_calls = tool_calls = outputs_cut = 0
    stopped: PlanStop = "turn_budget"
    start = f"{template.id}\n```python\n{template.code}\n```" if template is not None else "(none)"
    for rounds in range(1, cfg.max_rounds + 1):
        budget = cfg.max_turns - turns
        if rounds > 1:
            budget = min(budget, cfg.fix_turns)
        if budget <= 0:
            stopped = "turn_budget"
            break
        inner: PlanStop = "turn_budget"
        for left in range(budget, 0, -1):
            turns += 1
            user = prompt.render_user(
                intent=scrub_text(draft.intent),
                draft_lines=scrub_text("\n".join(f"{label}. {text}" for label, text in lines)),
                class_name=class_name,
                starting_point=scrub_text(start),
                transcript=transcript.render(),
                rows=scrub_text(_render_rows(rows)),
                feedback=feedback,
                turn=str(turns),
                max_turns=str(cfg.max_turns),
                turns_left=str(left - 1),
                max_actions=str(cfg.max_actions_per_turn),
            )
            result = complete_structured(
                client,
                LLMRequest(
                    messages=(
                        Message(role="system", content=prompt.system),
                        Message(role="user", content=user),
                    ),
                    temperature=settings.llm.temperature,
                    seed=settings.llm.seed,
                    max_output_tokens=min(settings.llm.max_output_tokens, 4000),
                    json_schema=strict_schema(PlannerStep),
                    model=model_name(settings, "plan"),
                ),
                PlannerStep,
                max_retries=settings.llm.max_retries_on_bad_json,
            )
            llm_calls += result.attempts
            step = result.value
            rows = list(step.rows) or rows  # an empty list never erases a plan
            if step.done:
                inner = "done"
                break
            if not step.actions:
                inner = "no_actions"
                break
            for action in step.actions[: cfg.max_actions_per_turn]:
                call = f"{action.tool}({action.arg!r})"
                if (action.tool, action.arg) in seen:
                    transcript.add(call, "(already run; see its output above)")
                    continue
                seen.add((action.tool, action.arg))
                output = tools.run(action)
                tool_calls += 1
                outputs_cut += "... (cut at " in output[-60:]
                transcript.add(call, output)
        checked = check_rows(rows, lines, class_name, index)
        failing = [r for r in checked if r.verdict in _SENT_BACK]
        stopped = inner
        if not failing:
            break
        if rounds == cfg.max_rounds:
            stopped = "round_cap"
            break
        sent_back.update(r.verdict for r in failing)
        feedback = _feedback(failing)
    final = [
        row
        if row.verdict not in ("missing", "no_member")
        else CheckedRow(  # a member that isn't there is a gap, named, never a guess
            line=row.line,
            kind="gap",
            member=row.member,
            note=row.note,
            verdict=row.verdict,
        )
        for row in checked
    ]
    return Plan(
        class_name=class_name,
        rows=final,
        turns=turns,
        max_turns=cfg.max_turns,
        rounds=rounds,
        max_rounds=cfg.max_rounds,
        stopped=stopped,
        near_cap=turns >= cfg.max_turns - 1 or (cfg.max_rounds > 1 and rounds >= cfg.max_rounds),
        sent_back=dict(sent_back),
        tool_calls=tool_calls,
        outputs_cut=outputs_cut,
        llm_calls=llm_calls,
    )


def plan_context(plan: Plan, draft: TestCaseDraft) -> str:
    """The plan as the writer reads it. Empty when the plan has no call or check to give."""
    if not any(r.kind in ("call", "check") for r in plan.rows):
        return ""
    text = dict(draft_lines(draft))
    out = [
        "Plan for the new test (each member was looked up in the suite for this draft; a "
        "correct test makes every call and check listed, in this order, also when the "
        "template doesn't; choose the arguments from the draft and the data):"
    ]
    for row in plan.rows:
        head = f"- {row.line} ({text.get(row.line, '')[:120]}): "
        if row.kind in ("call", "check"):
            out.append(head + f"{row.kind} `{row.member}`")
        elif row.kind == "seed":
            out.append(head + "comes from the entry's data, no call")
        else:
            out.append(
                head
                + "nothing in the suite does this"
                + (f" (`{row.member}` doesn't exist)" if row.member else "")
                + ": don't replace it with the closest call; leave the step out and name it "
                "under noted_missing"
            )
    return "\n".join(out)


def unmade(plan: Plan, generated: GeneratedTest) -> list[str]:
    """Planned calls and checks the new test doesn't make (by the member's name)."""
    wanted = {function_of(i) for i in (generated.new_test_ids or generated.test_ids)}
    try:
        tree = ast.parse(generated.code)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            names |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    return [
        r.member
        for r in plan.rows
        if r.kind in ("call", "check")
        and r.member.removesuffix("()").rpartition(".")[2] not in names
    ]
