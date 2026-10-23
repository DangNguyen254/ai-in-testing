"""Scale shapes from real suites: a cut chain list, very large areas, very large page objects."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import Settings
from ticket2test.gaps import check_pieces
from ticket2test.guides.context import area_guide_text
from ticket2test.guides.inputs import pick_material
from ticket2test.guides.run import save_guide
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.gaps import MissingPiece
from ticket2test.models.guide import AreaGuide, GuideOutput
from ticket2test.models.retrieval import InvestigatorAction
from ticket2test.retrieve.investigator import IndexTools
from ticket2test.retrieve.pipeline import Retriever
from ticket2test.suitemap import build_map

STANDIN = REPO_ROOT / "standin"


def _settings(folder: Path, **sections: Any) -> Settings:
    return Settings.model_validate({"paths": {"cache_dir": str(folder / "cache")}, **sections})


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    settings = _settings(tmp_path_factory.mktemp("full"))
    return settings, update_index(STANDIN, settings)[0]


@pytest.fixture(scope="module")
def cut(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    """The chain list cut to a handful of entries, as on a suite with hundreds of pages."""
    settings = _settings(tmp_path_factory.mktemp("cut"), index={"max_chain_entries": 5})
    return settings, update_index(STANDIN, settings)[0]


def test_page_objects_dont_depend_on_the_chain_list(
    full: tuple[Settings, IndexData], cut: tuple[Settings, IndexData]
) -> None:
    assert not full[1].catalog.chains_truncated
    assert cut[1].catalog.chains_truncated and len(cut[1].catalog.chains) <= 6
    assert cut[1].catalog.page_objects == full[1].catalog.page_objects  # found by types


def test_gap_check_and_chain_tool_work_with_a_cut_list(cut: tuple[Settings, IndexData]) -> None:
    settings, index = cut
    piece = MissingPiece(
        kind="page_object_member",
        owner="nav.rules.list",
        name="rule_count_total",
        needed_for="t",
        source="investigator",
    )
    (verdict,) = check_pieces([piece], index, settings)
    assert verdict.status == "close_match" and "RuleListPage.total_count" in verdict.close
    tools = IndexTools(Retriever(index, settings), settings.retrieval.investigator)
    out = tools.run(InvestigatorAction(tool="chain", arg="nav.rules"))
    assert "nav.rules.list (property" in out and "nav.rules.wizard" in out


def test_very_large_areas_are_split_by_module(full: tuple[Settings, IndexData]) -> None:
    settings, index = full
    small = settings.model_copy(
        update={"map": settings.map.model_copy(update={"max_tests_per_area": 5})}
    )
    names = [a.name for a in build_map(index, small).areas]
    assert "rules/test_rules" in names and "rules" not in names  # 15 tests, one module
    assert "agent/test_agent_api" in names  # several modules, one sub-area each
    assert "tenants" in names  # small areas stay whole
    assert (
        sum(a.tests for a in build_map(index, small).areas)
        == build_map(index, settings).overview.tests
    )


def test_large_page_objects_go_in_as_an_outline(full: tuple[Settings, IndexData]) -> None:
    settings, index = full
    rules = next(a for a in build_map(index, settings).areas if a.name == "rules")
    tight = settings.model_copy(
        update={"guides": settings.guides.model_copy(update={"max_piece_tokens": 200})}
    )
    material = pick_material(rules, index, tight)
    outline = [p for p in material.pieces if p.endswith("(outline)")]
    assert "Page object framework/pages/rules.py::RuleListPage (outline)" in outline
    block = material.text.split("RuleListPage (outline)")[1].split("### ")[0]
    lines = [line.strip() for line in block.splitlines() if line.startswith("    ")]
    assert any(line.startswith("def search(") for line in lines)
    assert any(line.startswith("search_text: property") for line in lines)
    used_first = lines.index(next(line for line in lines if line.startswith("def search(")))
    assert used_first < len(lines) - 1  # members the area uses come before the rest


def test_a_sub_area_guide_is_preferred(full: tuple[Settings, IndexData], tmp_path: Path) -> None:
    settings, index = full
    folder = tmp_path / "guides"
    for area in ("rules", "rules/test_rules"):
        save_guide(
            folder,
            AreaGuide(
                area=area,
                digest="d",
                sources={},
                model="m",
                prompt_version="guide_v1",
                built_at=datetime.now(UTC),
                input_pieces=[],
                input_tokens_estimate=0,
                guide=GuideOutput(
                    summary=f"guide for {area}",
                    how_to_add=[],
                    classes=[],
                    page_objects=[],
                    helpers=[],
                    data=[],
                    examples=[],
                    pitfalls=[],
                ),
            ),
        )
    local = settings.model_copy(
        update={"guides": settings.guides.model_copy(update={"dir": folder})}
    )
    text, label = area_guide_text(
        "rules", STANDIN, index, local, files=["tests/rules/test_rules.py"]
    )
    assert label == "rules/test_rules" and "guide for rules/test_rules" in text
    _, label = area_guide_text("rules", STANDIN, index, local)
    assert label == "rules"  # no file given: the area's guide
