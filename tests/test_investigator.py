"""The retrieval investigator: read-only tools, budgets, checked output (fake LLM only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm import FakeLLMClient
from ticket2test.models import Ticket
from ticket2test.models.retrieval import InvestigatorAction
from ticket2test.normalize import normalize
from ticket2test.retrieve.investigator import IndexTools, _Transcript
from ticket2test.retrieve.pipeline import Retriever, retrieve

STANDIN = REPO_ROOT / "standin"
EXPORT = STANDIN / "tickets" / "export.json"
ADD_BASIC = "tests/rules/test_rules.py::TestRules.test_rules_add_basic"


def _settings(tmp_path: Path, **investigator: Any) -> Settings:
    return Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "retrieval": {"investigator": {"enabled": True, **investigator}},
        }
    )


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("idx") / "cache")}}
    )
    data, _, _ = update_index(STANDIN, settings)
    return data


def _ticket(key: str) -> Ticket:
    return normalize(JiraExportSource(EXPORT).fetch(key))


def _rewrite() -> str:
    return json.dumps({"terms": ["rule"], "identifiers": [], "reason": "r"})


def _step(
    actions: list[tuple[str, str]] = (),  # type: ignore[assignment]
    keep: list[tuple[str, str]] = (),  # type: ignore[assignment]
    done: bool = False,
    missing: list[dict[str, str]] = (),  # type: ignore[assignment]
) -> str:
    return json.dumps(
        {
            "thought": "t",
            "actions": [{"tool": t, "arg": a} for t, a in actions],
            "keep": [{"chunk_id": c, "why": w} for c, w in keep],
            "missing": list(missing),
            "done": done,
        }
    )


def _tools(index: IndexData, tmp_path: Path, **cfg: Any) -> IndexTools:
    settings = _settings(tmp_path, **cfg)
    return IndexTools(Retriever(index, settings), settings.retrieval.investigator)


# --- tools ---------------------------------------------------------------------------


def test_tools_read_the_index(index: IndexData, tmp_path: Path) -> None:
    tools = _tools(index, tmp_path)

    def run(tool: str, arg: str) -> str:
        return tools.run(InvestigatorAction(tool=tool, arg=arg))  # type: ignore[arg-type]

    assert ADD_BASIC in run("search", "rules add basic")
    opened = run("open", ADD_BASIC)
    assert "test ids: test_rules_add_basic" in opened and "def test_rules_add_basic" in opened
    assert "nav.rules" in run("chain", "nav") and "nav.agent.console" not in run("chain", "nav")
    assert "nav.agent.console" in run("chain", "nav.agent")
    assert '"test_id": "test_rules_add_basic' in run("data", ADD_BASIC)
    assert ADD_BASIC in run("tests_using", "rules")
    assert ADD_BASIC in run("callers", "publish") and "[function]" in run("callers", "publish")
    assert run("open", "no/such.py::X").startswith("no chunk with id")
    assert "not a known identifier" in run("grep", "NoSuchThingAnywhere")


def test_tool_output_is_cut_to_the_budget(index: IndexData, tmp_path: Path) -> None:
    tools = _tools(index, tmp_path, max_tool_output_chars=200)
    out = tools.run(InvestigatorAction(tool="open", arg=ADD_BASIC))
    assert out.endswith("(cut at 200 characters)") and len(out) < 260


def test_the_transcript_drops_old_output_first() -> None:
    transcript = _Transcript(max_chars=1200)  # 5 blocks of ~416 chars
    for i in range(5):
        transcript.add(f"search('q{i}')", "x" * 400)
    text = transcript.render()
    assert text.count("output removed to fit the budget") == 3
    assert text.endswith("x" * 400)  # the latest output is always kept whole
    assert "search('q0')" in text  # the call itself stays visible


# --- the loop ------------------------------------------------------------------------


def test_done_stops_and_kept_chunks_reach_the_hits(index: IndexData, tmp_path: Path) -> None:
    fake = FakeLLMClient(
        [
            _rewrite(),
            _step(actions=[("search", "rules add"), ("open", ADD_BASIC)]),
            _step(keep=[(ADD_BASIC, "closest add test"), ("made/up.py::Nope", "x")], done=True),
        ]
    )
    result = retrieve(_ticket("STND-101"), index, _settings(tmp_path), fake)
    inv = result.investigation
    assert inv is not None and inv.stopped == "done" and inv.steps == 2
    assert [k.chunk_id for k in inv.kept] == [ADD_BASIC]
    assert inv.dropped_ids == ["made/up.py::Nope"]  # an id that doesn't exist is dropped
    assert inv.tool_calls[0].startswith("search('rules add')")
    assert result.followup_rounds == 0  # the investigator replaces the follow-up rounds
    assert result.llm_calls == 3 and result.prompt_versions[-1] == "investigator_v2"
    hit = next(h for h in result.hits if h.chunk_id == ADD_BASIC)
    assert any(r.source == "investigator" and r.detail == "closest add test" for r in hit.reasons)
    # Turn 2 saw turn 1's tool output, inside the untrusted-data tags.
    second = fake.requests[2].messages[1].content
    assert "<tool_outputs>" in second and "def test_rules_add_basic" in second


def test_the_step_budget_caps_the_loop(index: IndexData, tmp_path: Path) -> None:
    never_done = [_step(actions=[("search", f"query {i}")]) for i in range(10)]
    fake = FakeLLMClient([_rewrite(), *never_done])
    result = retrieve(_ticket("STND-102"), index, _settings(tmp_path, max_steps=3), fake)
    inv = result.investigation
    assert inv is not None and inv.stopped == "budget" and inv.steps == 3
    assert len(fake.requests) == 4  # 1 rewrite + exactly 3 turns


def test_actions_per_turn_are_capped_and_repeats_not_rerun(
    index: IndexData, tmp_path: Path
) -> None:
    many = [("search", f"q{i}") for i in range(5)]
    fake = FakeLLMClient(
        [
            _rewrite(),
            _step(actions=many),
            _step(actions=[("search", "q0")]),
            _step(done=True),
        ]
    )
    settings = _settings(tmp_path, max_actions_per_step=2)
    inv = retrieve(_ticket("STND-102"), index, settings, fake).investigation
    assert inv is not None
    assert [c.split(" ->")[0] for c in inv.tool_calls] == ["search('q0')", "search('q1')"]
    assert "(already run; see its output above)" in fake.requests[3].messages[1].content


def test_a_turn_without_actions_stops(index: IndexData, tmp_path: Path) -> None:
    hint = {"kind": "helper", "owner": "", "name": "delete_profile", "needed_for": "step 3"}
    fake = FakeLLMClient([_rewrite(), _step(missing=[hint])])
    inv = retrieve(_ticket("STND-102"), index, _settings(tmp_path), fake).investigation
    assert inv is not None and inv.stopped == "no_actions"
    assert [(m.kind, m.name) for m in inv.missing] == [("helper", "delete_profile")]


def test_bad_json_is_retried_within_the_limit(index: IndexData, tmp_path: Path) -> None:
    fake = FakeLLMClient([_rewrite(), "not json", _step(done=True)])
    inv = retrieve(_ticket("STND-102"), index, _settings(tmp_path), fake).investigation
    assert inv is not None and inv.llm_calls == 2 and inv.steps == 1


def test_disabled_by_default_keeps_the_follow_up_rounds(index: IndexData, tmp_path: Path) -> None:
    settings = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "c")}})
    assert settings.retrieval.investigator.enabled is False
    fake = FakeLLMClient([_rewrite()])
    assert retrieve(_ticket("STND-101"), index, settings, fake).investigation is None


def test_grep_says_when_a_name_exists_but_is_used_too_often(
    index: IndexData, tmp_path: Path
) -> None:
    """Haiku read "matches nothing, or too many chunks" as "doesn't exist" (verify_targets)."""
    tools = _tools(index, tmp_path)
    tools.retriever.cfg = tools.retriever.cfg.model_copy(update={"grep_max_matches": 2})
    out = tools.run(InvestigatorAction(tool="grep", arg="verify_targets"))
    assert out.startswith("'verify_targets' exists: it is used in")
    assert "framework/validations.py::ValidationMixin.verify_targets" in out
