"""The planning step (generate/planner.py) with the fake LLM, on the stand-in: the plan check,
the two capped loops and their counters, and the plan reaching the writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_generate import GOOD_CODE, STANDIN, TEMPLATE_CHUNK, _draft, _settings
from ticket2test.config import Settings
from ticket2test.generate.planner import (
    check_rows,
    draft_lines,
    make_plan,
    member_verdict,
    plan_context,
    unmade,
)
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm import FakeLLMClient
from ticket2test.models.plan import PlanRow


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    data, _, _ = update_index(STANDIN, _settings(tmp_path_factory.mktemp("idx")))
    return data


def _on(tmp_path: Path, **planner: Any) -> Settings:
    base = _settings(tmp_path)
    return base.model_copy(
        update={
            "generate": base.generate.model_copy(
                update={
                    "planner": base.generate.planner.model_copy(update={"enabled": True, **planner})
                }
            )
        }
    )


def _row(line: str, kind: str, member: str = "", note: str = "read it") -> dict[str, str]:
    return {"line": line, "kind": kind, "member": member, "note": note}


def _step(
    rows: list[dict[str, str]], actions: tuple[tuple[str, str], ...] = (), done: bool = False
) -> str:
    return json.dumps(
        {
            "thought": "looking",
            "actions": [{"tool": t, "arg": a} for t, a in actions],
            "rows": rows,
            "done": done,
        }
    )


GOOD = [
    _row("P1", "seed"),
    _row("S1", "call", "self.nav.rules.list.select_rule"),
    _row("S2", "call", "self.nav.rules.list.delete_selected"),
    _row("S2", "call", "self.nav.rules.confirm.confirm"),
    _row("S3", "call", "self.nav.top_bar.publish"),
    _row("E", "check", "self.verify_targets"),
]


def test_a_member_is_checked_the_way_a_tests_self_resolves(index: IndexData) -> None:
    assert member_verdict("self.nav.rules.list.delete_selected", "TestRules", index) == "ok"
    assert member_verdict("self.nav.rules.list.delete_selected()", "TestRules", index) == "ok"
    assert member_verdict("self.verify_targets", "TestRules", index) == "ok"  # inherited
    assert member_verdict("self.nav.rules.list.no_such_member", "TestRules", index) == "missing"
    assert member_verdict("self.no_such_helper", "TestRules", index) == "missing"
    # the catalog can't type what a dict returns: not an error
    assert member_verdict("self.params.get", "TestRules", index) == "unknown"
    assert member_verdict("self.nav.rules.list.open", "NoSuchClass", index) == "unknown"
    assert member_verdict("", "TestRules", index) == "no_member"


def test_every_draft_line_gets_a_row_or_a_gap(index: IndexData) -> None:
    lines = draft_lines(_draft())
    assert [label for label, _ in lines] == ["P1", "S1", "S2", "S3", "E"]
    rows = [PlanRow(**r) for r in GOOD if r["line"] != "S3"] + [PlanRow(**_row("S9", "seed"))]
    checked = check_rows(rows, lines, "TestRules", index)
    assert [(r.line, r.verdict) for r in checked if r.verdict != "ok"] == [("S3", "not_planned")]
    assert all(r.line != "S9" for r in checked)  # a line the draft doesn't have is dropped
    assert [r.line for r in checked] == ["P1", "S1", "S2", "S2", "S3", "E"]


def test_a_failing_row_is_sent_back_once_and_counted(index: IndexData, tmp_path: Path) -> None:
    """Round 1: a lookup, then a plan with a member that doesn't exist and a line left out.
    Code sends both back; round 2 fixes them within its small budget."""
    template = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    wrong = [r for r in GOOD if r["line"] not in ("S3", "E")] + [
        _row("E", "check", "self.verify_everything")
    ]
    fake = FakeLLMClient(
        [
            _step([], (("list_members", "TestRules"), ("chain", "nav.rules"))),
            _step(wrong, done=True),
            _step(GOOD, done=True),
        ]
    )
    plan = make_plan(_draft(), template, "TestRules", index, _on(tmp_path), fake)
    assert (plan.turns, plan.rounds, plan.stopped) == (3, 2, "done")
    assert plan.sent_back == {"not_planned": 1, "missing": 1} and plan.tool_calls == 2
    assert plan.near_cap  # the last allowed round was used
    assert [r.verdict for r in plan.rows] == ["ok"] * 6
    second, third = (r.messages[1].content for r in fake.requests[1:])
    assert "list_members('TestRules')" in second and "verify_targets" in second  # tool output
    assert "- E `self.verify_everything`: the class this leads to has no such member" in third
    assert "- S3: no row covers this draft line" in third
    assert "Turn 3 of 8" in third

    text = plan_context(plan, _draft())
    assert "- S1 (Select one rule): call `self.nav.rules.list.select_rule`" in text
    assert "- P1 (A policy with three rules): comes from the entry's data, no call" in text
    assert plan.summary().startswith("done, 3/8 turn(s), 2/2 round(s), near cap yes; call 4")


def test_what_still_fails_after_the_last_round_is_a_gap_not_a_guess(
    index: IndexData, tmp_path: Path
) -> None:
    template = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    wrong = [r for r in GOOD if r["line"] != "E"] + [_row("E", "check", "self.verify_everything")]
    fake = FakeLLMClient([_step(wrong, done=True), _step(wrong, done=True)])
    plan = make_plan(_draft(), template, "TestRules", index, _on(tmp_path), fake)
    assert (plan.turns, plan.rounds, plan.stopped) == (2, 2, "round_cap")
    last = plan.rows[-1]
    assert (last.line, last.kind, last.verdict) == ("E", "gap", "missing")
    text = plan_context(plan, _draft())
    assert "nothing in the suite does this (`self.verify_everything` doesn't exist)" in text
    assert "check `self.verify_everything`" not in text


def test_the_turn_budget_is_shared_and_never_exceeded(index: IndexData, tmp_path: Path) -> None:
    """A planner that keeps looking gets ``max_turns`` calls in all, and its last rows count."""
    template = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    looking = [_step(GOOD[:2], (("grep", f"name_{n}"),)) for n in range(10)]
    fake = FakeLLMClient(looking)
    settings = _on(tmp_path, max_turns=3)
    plan = make_plan(_draft(), template, "TestRules", index, settings, fake)
    assert len(fake.requests) == 3 and plan.turns == 3
    assert plan.stopped == "turn_budget" and plan.near_cap
    assert plan.outputs_dropped == 0 and plan.summary().endswith("3 lookup(s), 0 cut, 0 dropped")
    assert [r.verdict for r in plan.rows].count("not_planned") == 3  # S2, S3, E: gaps


def test_planned_members_the_test_lacks_are_listed(index: IndexData, tmp_path: Path) -> None:
    from ticket2test.models.generated import GeneratedTest

    template = next(c for c in index.chunks if c.id == TEMPLATE_CHUNK)
    rows = [*GOOD, _row("S3", "call", "self.nav.top_bar.reset")]
    fake = FakeLLMClient([_step(rows, done=True)])
    plan = make_plan(_draft(), template, "TestRules", index, _on(tmp_path), fake)
    assert "publish" in GOOD_CODE and "reset" not in GOOD_CODE
    generated = GeneratedTest.model_construct(
        code=GOOD_CODE, test_ids=["test_rules_delete_keeps_others[first]"], new_test_ids=[]
    )
    assert unmade(plan, generated) == ["self.nav.top_bar.reset"]


def test_the_plan_reaches_the_writer_only_when_switched_on(
    index: IndexData, tmp_path: Path
) -> None:
    from tests.test_patch import _ticketed
    from tests.test_reuse import SCENARIOS
    from ticket2test.generate.pipeline import generate_reusing

    draft = SCENARIOS["method"][0]
    rows = [_row(label, "check", "self.verify_targets") for label, _ in draft_lines(draft)]
    settings = _on(tmp_path)
    fake = FakeLLMClient([_step(rows, done=True)])  # the plan, then generation runs out
    with pytest.raises(Exception, match="exhausted"):
        generate_reusing(
            draft, _ticketed(settings, index, draft), index, settings, fake, "f", "m", STANDIN
        )
    assert "planning one automated test" in fake.requests[0].messages[0].content
    written = "\n".join(m.content for m in fake.requests[-1].messages)
    assert "Plan for the new test" in written and "check `self.verify_targets`" in written

    off = _settings(tmp_path)
    fake = FakeLLMClient([])
    with pytest.raises(Exception, match="exhausted"):
        generate_reusing(draft, _ticketed(off, index, draft), index, off, fake, "f", "m", STANDIN)
    assert len(fake.requests) == 1
    assert all("Plan for the new test" not in m.content for m in fake.requests[-1].messages)
