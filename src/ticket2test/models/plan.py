"""The planning step's models (generate/planner.py): what the model returns each turn, and the
plan after code checked it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.models.retrieval import InvestigatorAction

PlanKind = Literal["call", "check", "seed", "gap"]
# ok: the member exists; unknown: the catalog can't type the chain (not an error); missing: the
# class it leads to has no such member; no_member: a call or check row without a member;
# not_planned: a draft line no row covers (added by code).
RowVerdict = Literal["ok", "unknown", "missing", "no_member", "not_planned"]
PlanStop = Literal["done", "turn_budget", "round_cap", "no_actions"]


class PlanRow(BaseModel):
    """One draft line and what does it. ``member`` is written as the test would write it
    (``self.nav.rules.list.add_rule``, ``self.verify_targets``); empty for seed and gap rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    line: str = Field(min_length=1, max_length=8)  # the draft line's label: P1, S3, E
    kind: PlanKind
    member: str = Field(max_length=200)
    note: str = Field(max_length=300)  # what was read that led to the choice, or what is missing


class PlannerStep(BaseModel):
    """What the planner returns each turn (``prompts/planner_v*.md``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    thought: str = Field(max_length=600)
    actions: list[InvestigatorAction] = Field(max_length=6)
    rows: list[PlanRow] = Field(max_length=60)  # the whole plan so far (replaces the last one)
    done: bool


class CheckedRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    line: str
    kind: PlanKind
    member: str
    note: str
    verdict: RowVerdict


class Plan(BaseModel):
    """The plan code accepted, with how the run went (shown in the golden report)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    class_name: str  # the class ``self`` was resolved through
    rows: list[CheckedRow]
    turns: int
    max_turns: int
    rounds: int
    max_rounds: int
    stopped: PlanStop
    near_cap: bool  # within one turn of the budget, or the last round was used
    sent_back: dict[str, int] = Field(default_factory=dict)  # verdict -> rows sent back
    tool_calls: int = 0
    outputs_cut: int = 0  # tool outputs cut at the per-output cap
    # Tool outputs no longer shown to the model when it last answered (the transcript cap).
    outputs_dropped: int = 0
    llm_calls: int = 0

    def summary(self) -> str:
        """Counts only: safe in a log."""
        kinds = {k: sum(r.kind == k for r in self.rows) for k in ("call", "check", "seed", "gap")}
        unknown = sum(r.verdict == "unknown" for r in self.rows)
        return (
            f"{self.stopped}, {self.turns}/{self.max_turns} turn(s), {self.rounds}/"
            f"{self.max_rounds} round(s), near cap {'yes' if self.near_cap else 'no'}; "
            + ", ".join(f"{k} {n}" for k, n in kinds.items())
            + f", unknown {unknown}, {self.tool_calls} lookup(s), {self.outputs_cut} cut, "
            f"{self.outputs_dropped} dropped"
        )
