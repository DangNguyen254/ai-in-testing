"""Area guides: picked material, budget and ceiling, caching, the name check, and the
generation context. The LLM is always a fake."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import REPO_ROOT
from tests.test_meter import PricedFake
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.guides import BudgetError, load_guide, run_guides
from ticket2test.guides.check import check_guide
from ticket2test.guides.context import area_guide_text
from ticket2test.guides.inputs import pick_material
from ticket2test.guides.render import guide_context
from ticket2test.guides.run import save_guide
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm import FakeLLMClient
from ticket2test.models.guide import AreaGuide, GuideOutput
from ticket2test.models.suite_map import SuiteMap
from ticket2test.suitemap import build_map

STANDIN = REPO_ROOT / "standin"
ADD = "tests/rules/test_rules.py::TestRules.test_rules_add_with_condition"


def _settings(tmp_path: Path, **guides: Any) -> Settings:
    return Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "guides": {"dir": str(tmp_path / "guides"), **guides},
        }
    )


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    folder = tmp_path_factory.mktemp("idx")
    data, _, _ = update_index(STANDIN, _settings(folder))
    return data


@pytest.fixture(scope="module")
def suite_map(index: IndexData) -> SuiteMap:
    return build_map(index, Settings())


def _guide(**changes: Any) -> dict[str, Any]:
    guide: dict[str, Any] = {
        "summary": "Rules tests add, edit and delete rules, then publish and check the policy.",
        "how_to_add": [
            "Add a method to `TestRules`.",
            "Open `nav.rules.list`, call `add_rule()`, fill the wizard, `save()`.",
            "Publish with `nav.top_bar.publish()` and call `verify_targets()`.",
        ],
        "classes": [{"name": "TestRules", "use": "every rules test"}],
        "page_objects": [
            {"name": "nav.rules.list", "use": "the rule list"},
            {"name": "nav.rules.wizard", "use": "the add wizard"},
            {"name": "nav.rules.gadgets", "use": "invented"},
        ],
        "helpers": [
            {"name": "unique_name", "use": "a unique rule name"},
            {"name": "make_everything_work", "use": "invented"},
        ],
        "data": ["Seed `settings` and `policy`; expect `targets` with a GET of the rules."],
        "examples": [
            {"name": ADD, "use": "add shape"},
            {"name": "tests/rules/test_rules.py::TestRules.test_nope", "use": "invented"},
        ],
        "pitfalls": ["Call `refresh_everything()` first.", "Use `{test_id:24}` for names."],
    }
    guide.update(changes)
    return guide


def _replies(n: int) -> list[str]:
    return [json.dumps(_guide()) for _ in range(n)]


def _run(index: IndexData, suite_map: SuiteMap, settings: Settings, client: Any, **kw: Any) -> Any:
    assert settings.guides.dir is not None
    return run_guides(suite_map, index, settings, client, settings.guides.dir, **kw)


# --- material and the name check -----------------------------------------------------


def test_material_is_picked_whole_within_the_cap(index: IndexData, suite_map: SuiteMap) -> None:
    rules = next(a for a in suite_map.areas if a.name == "rules")
    full = pick_material(rules, index, Settings())
    assert full.pieces[0].startswith("Area summary") and not full.skipped
    assert f"Typical test {ADD}" in full.pieces
    assert "Page object framework/pages/rules.py::RuleListPage" in full.pieces
    assert "Helper framework/validations.py::ValidationMixin.verify_targets" in full.pieces
    small = pick_material(
        rules, index, Settings.model_validate({"guides": {"max_input_tokens": 2500}})
    )
    assert small.tokens <= 2500 and small.skipped
    assert small.pieces[0].startswith("Area summary")  # the summary always goes in


def test_the_check_removes_invented_names(index: IndexData, suite_map: SuiteMap) -> None:
    rules = next(a for a in suite_map.areas if a.name == "rules")
    checked, removed, unverified = check_guide(GuideOutput(**_guide()), rules, index)
    assert [r.name for r in checked.page_objects] == ["nav.rules.list", "nav.rules.wizard"]
    assert [r.name for r in checked.helpers] == ["unique_name"]
    assert [r.name for r in checked.examples] == [ADD]
    assert len(removed) == 3 and all("not in the index" in r for r in removed)
    assert unverified == ["refresh_everything()"]  # prose: flagged, not removed
    # literal values such as the placeholder aren't names


def test_names_the_suite_uses_are_not_flagged(index: IndexData, suite_map: SuiteMap) -> None:
    """False alarms from the first real run: unittest assertions (used by the tests, defined
    outside the repo), nested data keys, request methods, decorator values, JSON literals."""
    api = next(a for a in suite_map.areas if a.name == "api")
    guide = GuideOutput(
        **_guide(
            helpers=[{"name": "self.check.assertEqual", "use": "the assertion object"}],
            data=["`targets` items have `method`, `path`, `payload`, `status_code`, `response`."],
            pitfalls=["`GET` vs `PUT`; `cloud` and `on_prem`; `true` in JSON."],
            how_to_add=["Call `delete_test()` first."],
        )
    )
    checked, removed, unverified = check_guide(guide, api, index)
    assert [h.name for h in checked.helpers] == ["self.check.assertEqual"]
    assert not any("assertEqual" in r for r in removed)
    assert "delete_test()" in unverified  # a vague name the model made up is still flagged
    for word in ("method", "payload", "status_code", "GET", "PUT", "cloud", "on_prem", "true"):
        assert word not in unverified


def test_class_helpers_are_in_the_material(index: IndexData, suite_map: SuiteMap) -> None:
    """A real guide said a class helper was "not shown in the material": the scaffold now
    carries the class's own non-test methods, not only setup/teardown."""
    profiles = next(a for a in suite_map.areas if a.name == "profiles")
    material = pick_material(profiles, index, Settings())
    assert "def _add_profile(" in material.text


# --- estimate, budget, ceiling ---------------------------------------------------------


def test_an_estimate_calls_nothing(index: IndexData, suite_map: SuiteMap, tmp_path: Path) -> None:
    run = _run(index, suite_map, _settings(tmp_path), None, estimate_only=True)
    assert [i.area for i in run.items][:2] == ["exceptions", "rules"]  # most tests first
    assert {i.status for i in run.items} == {"planned"} and run.spent_usd == 0
    first = run.items[0]
    # Worst case of one call: prompt + the CLI overhead in, the output allowance out (Sonnet).
    expected = ((first.input_tokens_estimate + 25000) * 2.0 + 8000 * 10.0) / 1_000_000
    assert first.cost_estimate_usd == pytest.approx(expected)
    assert run.prices_known and run.model == "claude-sonnet-5-5"
    assert (run.overhead_tokens, run.output_allowance_tokens) == (25000, 8000)


_LEAN = {"call_overhead_tokens": 0, "output_allowance_tokens": 4000}  # ~$0.05 per call


def test_the_budget_stops_before_a_call_could_exceed_it(
    index: IndexData, suite_map: SuiteMap, tmp_path: Path
) -> None:
    fake = PricedFake(_replies(10), cost=0.01)
    run = _run(index, suite_map, _settings(tmp_path, **_LEAN), fake, budget_usd=0.06)
    statuses = [i.status for i in run.items]
    assert statuses[:2] == ["built", "over_budget"]  # one worst case fits, two don't
    assert statuses[2:] == ["stopped"] * (len(statuses) - 2)
    assert run.spent_usd == pytest.approx(0.01) and len(fake.requests) == 1
    assert "would exceed the budget" in run.stopped


def test_retries_are_checked_against_the_budget_too(
    index: IndexData, suite_map: SuiteMap, tmp_path: Path
) -> None:
    """Found on the first real run: retries made three calls per area while the budget was
    checked once per area, and the run went over."""
    settings = _settings(tmp_path, call_overhead_tokens=0, output_allowance_tokens=1000)
    fake = PricedFake(["not json"] * 10, cost=0.03)  # every attempt fails validation
    run = _run(index, suite_map, settings, fake, budget_usd=0.07, areas=["rules"])
    (item,) = run.items
    assert len(fake.requests) == 2  # the third attempt's worst case didn't fit
    assert item.status == "failed" and "would exceed the budget" in item.note
    assert run.spent_usd == pytest.approx(0.06) and run.spent_usd <= 0.07


def test_calibration_learns_from_real_calls(
    index: IndexData, suite_map: SuiteMap, tmp_path: Path
) -> None:
    class Heavy(PricedFake):
        def complete(self, request: Any) -> Any:
            response = super().complete(request)
            return response.model_copy(update={"input_tokens": 60000, "output_tokens": 9000})

    settings = _settings(tmp_path)
    folder = settings.guides.dir
    assert folder is not None
    run = _run(index, suite_map, settings, Heavy(_replies(1), cost=0.02), areas=["rules"])
    prompt = run.items[0].input_tokens_estimate
    saved = json.loads((folder / "calibration.json").read_text(encoding="utf-8"))
    assert saved["claude-sonnet-5-5"]["output_tokens"] == 9000
    assert saved["claude-sonnet-5-5"]["overhead_tokens"] >= 60000 - prompt - 10  # ~ the excess
    estimate = _run(index, suite_map, settings, None, estimate_only=True, force=True)
    assert estimate.output_allowance_tokens == 9000  # the next estimate uses what was seen
    assert estimate.overhead_tokens == saved["claude-sonnet-5-5"]["overhead_tokens"]
    # Measured numbers never lower the configured defaults.
    (folder / "calibration.json").write_text(
        json.dumps({"claude-sonnet-5-5": {"overhead_tokens": 5, "output_tokens": 5, "calls": 1}}),
        encoding="utf-8",
    )
    low = _run(index, suite_map, settings, None, estimate_only=True, force=True)
    assert (low.overhead_tokens, low.output_allowance_tokens) == (25000, 8000)


def test_the_ceiling_cant_be_passed(index: IndexData, suite_map: SuiteMap, tmp_path: Path) -> None:
    with pytest.raises(BudgetError, match="max_budget_usd"):
        _run(index, suite_map, _settings(tmp_path), None, budget_usd=50.01)
    lowered = _settings(tmp_path, max_budget_usd=5.0)
    with pytest.raises(BudgetError):
        _run(index, suite_map, lowered, None, budget_usd=6.0)


def test_no_price_means_no_call(index: IndexData, suite_map: SuiteMap, tmp_path: Path) -> None:
    fake = PricedFake(_replies(10))
    run = _run(index, suite_map, _settings(tmp_path, prices={}), fake)
    assert fake.requests == [] and run.items[0].status == "over_budget"
    assert "no price configured" in run.stopped
    assert {i.status for i in run.items[1:]} == {"stopped"}


def test_cost_from_tokens_when_the_provider_reports_none(
    index: IndexData, suite_map: SuiteMap, tmp_path: Path
) -> None:
    fake = PricedFake(_replies(1), cost=None)  # 100 input, 10 output tokens
    run = _run(index, suite_map, _settings(tmp_path), fake, areas=["rules"])
    (item,) = run.items
    assert item.status == "built"
    assert item.cost_usd == pytest.approx((100 * 2.0 + 10 * 10.0) / 1_000_000)


def test_unknown_cost_stops_the_run(index: IndexData, suite_map: SuiteMap, tmp_path: Path) -> None:
    fake = FakeLLMClient(_replies(10))  # reports neither cost nor tokens
    run = _run(index, suite_map, _settings(tmp_path), fake)
    assert run.items[0].status == "failed" and "neither a cost nor tokens" in run.stopped
    assert len(fake.requests) == 1


# --- building, caching, staleness ---------------------------------------------------------


def test_build_store_and_skip_when_up_to_date(
    index: IndexData, suite_map: SuiteMap, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    folder = settings.guides.dir
    assert folder is not None
    fake = PricedFake(_replies(8), cost=0.02)
    run = _run(index, suite_map, settings, fake)
    assert [i.status for i in run.items] == ["built"] * 8 and run.spent_usd == pytest.approx(0.16)
    guide = load_guide(folder, "rules")
    assert guide is not None and guide.model == "claude-sonnet-5-5"
    assert guide.digest == next(a.digest for a in suite_map.areas if a.name == "rules")
    assert guide.cost_usd == pytest.approx(0.02) and len(guide.removed) == 3
    assert (folder / "rules.md").read_text(encoding="utf-8").startswith("# Area guide: rules")
    # The material sent is the picked one, inside the untrusted-data tags.
    assert "<material>" in fake.requests[0].messages[1].content

    again = PricedFake([], cost=0.02)
    run = _run(index, suite_map, settings, again)
    assert {i.status for i in run.items} == {"up_to_date"} and again.requests == []

    stale = guide.model_copy(update={"digest": "changed"})
    save_guide(folder, stale)  # the area changed since: only that one is rebuilt
    third = PricedFake(_replies(1), cost=0.02)
    run = _run(index, suite_map, settings, third)
    assert [i.area for i in run.items if i.status == "built"] == ["rules"]

    forced = PricedFake(_replies(8), cost=0.02)
    run = _run(index, suite_map, settings, forced, force=True)
    assert len(forced.requests) == 8


def test_a_failed_area_doesnt_stop_the_others(
    index: IndexData, suite_map: SuiteMap, tmp_path: Path
) -> None:
    replies = ["not json"] * 3 + _replies(1)  # 1 try + 2 retries fail, then the next area
    fake = PricedFake(replies, cost=0.01)
    run = _run(index, suite_map, _settings(tmp_path), fake, areas=["rules", "agent"])
    assert [i.status for i in run.items] == ["failed", "built"]
    assert run.items[0].cost_usd == pytest.approx(0.03)  # the failed calls still cost
    assert run.spent_usd == pytest.approx(0.04)


def test_the_area_limit_per_run(index: IndexData, suite_map: SuiteMap, tmp_path: Path) -> None:
    fake = PricedFake(_replies(8), cost=0.01)
    run = _run(index, suite_map, _settings(tmp_path, max_areas_per_run=2), fake)
    assert [i.status for i in run.items].count("built") == 2
    assert [i.status for i in run.items].count("over_limit") == 6


# --- the generation context ---------------------------------------------------------------


def _stored(folder: Path, area: str, sources: dict[str, str]) -> AreaGuide:
    guide = AreaGuide(
        area=area,
        digest="d",
        sources=sources,
        model="m",
        prompt_version="guide_v1",
        built_at=datetime.now(UTC),
        input_pieces=[],
        input_tokens_estimate=0,
        guide=GuideOutput(**_guide()),
    )
    save_guide(folder, guide)
    return guide


def test_guide_context_fits_and_drops_whole_sections(tmp_path: Path) -> None:
    guide = _stored(tmp_path, "rules", {})
    full = guide_context(guide, 5000, 3.0)
    assert "#### How to add a test here" in full and "#### Examples to copy" in full
    short = guide_context(guide, 120, 3.0)
    assert len(short) / 3.0 <= 120 and "#### Summary" in short
    assert "#### Examples to copy" not in short


def test_a_stale_guide_is_labelled(index: IndexData, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.guides.dir is not None
    rules_sha = index.files["framework/pages/rules.py"].sha256
    _stored(settings.guides.dir, "rules", {"framework/pages/rules.py": rules_sha})
    text, label = area_guide_text("rules", STANDIN, index, settings)
    assert text.startswith("Area guide for `rules`") and label == "rules"
    _stored(settings.guides.dir, "rules", {"framework/pages/rules.py": "old"})
    _, label = area_guide_text("rules", STANDIN, index, settings)
    assert label == "rules (stale: 1 file(s) changed)"
    assert area_guide_text("nowhere", STANDIN, index, settings) == ("", "")


def test_generation_gets_the_area_guide(
    index: IndexData, suite_map: SuiteMap, tmp_path: Path
) -> None:
    from tests.test_patch import _ticketed
    from tests.test_reuse import SCENARIOS
    from ticket2test.generate.pipeline import generate_reusing

    settings = _settings(tmp_path)
    assert settings.guides.dir is not None
    for area in suite_map.areas:
        _stored(settings.guides.dir, area.name, {})
    draft = SCENARIOS["method"][0]
    fake = FakeLLMClient([])  # records the generation request, then runs out
    with pytest.raises(Exception, match="exhausted"):
        generate_reusing(
            draft, _ticketed(settings, index, draft), index, settings, fake, "f", "m", STANDIN
        )
    prompt = "\n".join(m.content for m in fake.requests[-1].messages)
    assert "Area guide for `" in prompt and "How to add a test here" in prompt

    off = _settings(tmp_path, use_in_generation=False)
    fake = FakeLLMClient([])
    with pytest.raises(Exception, match="exhausted"):
        generate_reusing(draft, _ticketed(off, index, draft), index, off, fake, "f", "m", STANDIN)
    assert all("Area guide for" not in m.content for m in fake.requests[-1].messages)


def test_cli_estimate_and_refused_budget(tmp_path: Path) -> None:
    env = {"T2T_PATHS__CACHE_DIR": str(tmp_path / "cache")}
    out = tmp_path / "guides"
    result = CliRunner().invoke(
        app, ["guides", str(STANDIN), "--estimate", "--out", str(out)], env=env
    )
    assert result.exit_code == 0, result.output
    assert "Area guides: estimate" in result.output and "| rules | 15 | planned |" in result.output
    assert list((out / "runs").glob("estimate-*.json"))
    refused = CliRunner().invoke(
        app, ["guides", str(STANDIN), "--estimate", "--budget", "80", "--out", str(out)], env=env
    )
    assert refused.exit_code == 2 and "max_budget_usd" in refused.output
