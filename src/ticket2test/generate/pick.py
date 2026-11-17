"""Picking members from the usage table: one model call maps each draft line to rows of the
table of the class the test goes into (and its folder). The model picks by label from a closed
list; code drops labels it wasn't shown. No lookups, no code written.

This is step 3 of the usage-table plan (docs/design-step-status.md): measured alone, against
the reference test's calls, before it is wired into generation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import Settings
from ticket2test.generate.planner import draft_lines
from ticket2test.index.indexer import IndexData
from ticket2test.index.usage import CallUse, render_scope, usage_table
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.draft import TestCaseDraft
from ticket2test.prompts import load_prompt
from ticket2test.security import scrub_text


class LinePick(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    line: str = Field(min_length=1, max_length=8)  # P1, S2, E
    rows: list[str] = Field(max_length=8)  # U labels, in the order the test makes the calls


class PickReply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    picks: list[LinePick] = Field(max_length=60)


def table_rows(
    index: IndexData,
    settings: Settings,
    file_path: str,
    class_name: str | None,
    exclude: set[str] | None = None,
) -> list[CallUse]:
    """The class's calls, most used first, then its folder's calls the class doesn't make."""
    table = usage_table(index, settings)
    mine = table.scope(index, file_path=file_path, class_name=class_name, exclude=exclude)
    seen = {u.call for u in mine}
    folder = table.scope(index, folder=file_path.rpartition("/")[0], exclude=exclude)
    return mine + [u for u in folder if u.call not in seen]


def pick_rows(
    draft: TestCaseDraft,
    rows: list[CallUse],
    class_name: str,
    settings: Settings,
    client: LLMClient,
) -> tuple[dict[str, list[str]], int, int]:
    """(draft line -> the calls picked for it, in order; labels dropped as not shown; LLM
    calls). Only the first ``generate.pick.max_rows`` rows are shown."""
    cfg = settings.generate.pick
    shown = rows[: cfg.max_rows]
    prompt = load_prompt(cfg.prompt, settings.paths.prompts_dir)
    lines = draft_lines(draft)
    user = prompt.render_user(
        intent=scrub_text(draft.intent),
        draft_lines=scrub_text("\n".join(f"{label}. {text}" for label, text in lines)),
        class_name=class_name,
        rows=scrub_text(render_scope(shown, cfg.max_rows)) or "(no rows)",
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
            max_output_tokens=min(settings.llm.max_output_tokens, 2000),
            json_schema=strict_schema(PickReply),
            model=model_name(settings, "pick"),
        ),
        PickReply,
        max_retries=settings.llm.max_retries_on_bad_json,
    )
    labels = {f"U{n}": use.call for n, use in enumerate(shown, 1)}
    known = {label for label, _ in lines}
    picked: dict[str, list[str]] = {}
    dropped = 0
    for pick in result.value.picks:
        line = pick.line.strip().upper()
        if line not in known:
            dropped += len(pick.rows)
            continue
        for label in pick.rows:
            call = labels.get(label.strip().upper())
            if call is None:
                dropped += 1
            elif call not in picked.setdefault(line, []):
                picked[line].append(call)
    return picked, dropped, result.attempts
