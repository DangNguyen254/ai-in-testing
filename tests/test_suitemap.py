"""The suite map: area summaries built from the index by code (no LLM)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import REPO_ROOT
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.suite_map import SuiteMap
from ticket2test.suitemap import build_map, load_map, write_map

STANDIN = REPO_ROOT / "standin"


def _settings(tmp_path: Path, **sections: Any) -> Settings:
    return Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}, **sections})


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    data, _, _ = update_index(STANDIN, _settings(tmp_path_factory.mktemp("idx")))
    return data


@pytest.fixture(scope="module")
def suite_map(index: IndexData, tmp_path_factory: pytest.TempPathFactory) -> SuiteMap:
    return build_map(index, _settings(tmp_path_factory.mktemp("map")))


def _area(m: SuiteMap, name: str) -> Any:
    return next(a for a in m.areas if a.name == name)


def test_areas_cover_every_test(index: IndexData, suite_map: SuiteMap) -> None:
    own_tests = [c for c in index.chunks if c.kind == "test" and not c.inherited_from]
    assert [a.name for a in suite_map.areas] == [
        "agent", "api", "exceptions", "files", "profiles", "reports", "rules", "settings",
        "tenants", "units",
    ]  # fmt: skip
    assert sum(a.tests for a in suite_map.areas) == len(own_tests) == suite_map.overview.tests
    assert suite_map.overview.unassigned_tests == []
    for area in suite_map.areas:
        in_area = [t for t in own_tests if t.file_path.startswith(area.folders[0] + "/")]
        assert area.tests == len(in_area)
        assert area.test_ids == sum(len(t.test_ids) for t in in_area)


def test_an_area_says_how_its_tests_are_built(suite_map: SuiteMap) -> None:
    rules = _area(suite_map, "rules")
    (cls,) = rules.classes
    assert cls.name == "TestRules" and cls.bases == ["BaseTest"]
    assert "data_driven" in cls.decorators
    assert cls.setup_calls == ["setup: base_setup(fresh_driver=False, policy_wait=True)"]
    assert {c.name for c in rules.chains} >= {"nav.rules.list", "nav.top_bar"}
    assert {c.name for c in rules.page_actions} >= {"open", "save", "publish"}
    assert {c.name for c in rules.base_helpers} == {"unique_name", "verify_targets"}
    assert {c.name for c in rules.assertions} >= {"assertEqual"}
    assert rules.data_key_roles["settings"] == "seed"
    assert rules.data_key_roles["targets"] == "expectation"
    assert rules.data_key_roles["priority"] == "per entry"
    assert rules.data_key_roles["total_count"] == "read by the test"
    # Version segments stay; only all-digit path segments would be normalized.
    assert [e.name for e in rules.expectations] == [
        "targets: GET /api/policy/v1/rules/:tid/:rev_id"
    ]
    assert {p.name for p in rules.placeholders} >= {"{test_id:24}"}


def test_examples_are_real_tests_of_the_area(index: IndexData, suite_map: SuiteMap) -> None:
    ids = {c.id for c in index.chunks if c.kind == "test"}
    for area in suite_map.areas:
        assert area.examples, area.name
        for example in area.examples:
            assert example in ids and example.startswith(area.folders[0] + "/")


def test_sources_and_digest(index: IndexData, suite_map: SuiteMap, tmp_path: Path) -> None:
    rules = _area(suite_map, "rules")
    assert {
        "tests/rules/test_rules.py", "tests/rules/test_rules.json", "framework/pages/rules.py",
        "framework/base_test.py", "framework/validations.py", "framework/decorators.py",
    } <= set(rules.sources)  # fmt: skip
    files = _area(suite_map, "files")
    assert "tests/files/checks.py" in files.sources  # an in-folder base class
    again = build_map(index, _settings(tmp_path))
    assert [a.digest for a in again.areas] == [a.digest for a in suite_map.areas]
    assert again.changed_areas is None  # no previous map given


def test_changed_areas_against_a_previous_map(index: IndexData, suite_map: SuiteMap) -> None:
    previous = suite_map.model_copy(deep=True)
    previous.areas[0].digest = "stale"
    previous.areas = previous.areas[:-1]  # an area the old map didn't have counts as changed
    rebuilt = build_map(index, Settings(), previous=previous)
    assert rebuilt.changed_areas == [suite_map.areas[0].name, suite_map.areas[-1].name]


def test_coverage_lists_only_unreferenced_test_side_code(suite_map: SuiteMap) -> None:
    gaps = {(g.kind, g.name) for g in suite_map.coverage}
    assert ("page_member", "RuleListPage.page_count") in gaps
    assert ("page_member", "DeleteConfirmPage.cancel") in gaps
    names = {name for _, name in gaps}
    assert "BasePage.click" not in names  # used inside other page objects
    assert not any(kind == "base_helper" for kind, _ in gaps)  # setup hooks are pytest's
    assert not any(name.startswith("framework.decorators.") for name in names)  # decorators
    assert not any(g.file_path.startswith("app/") for g in suite_map.coverage)  # product code


def test_folders_are_areas_when_no_domain_glob_matches(index: IndexData, tmp_path: Path) -> None:
    settings = _settings(tmp_path, generate={"domain_globs": ["nothing/*"]})
    m = build_map(index, settings)
    assert [a.folders for a in m.areas][:2] == [["tests/agent"], ["tests/api"]]


def test_a_suite_without_classes_or_page_objects(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_plain.py").write_text(
        'import pytest\n\n\n@pytest.mark.parametrize("n", [1, 2])\ndef test_plain(n):\n'
        "    assert n\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    index, _, _ = update_index(repo, settings)
    m = build_map(index, settings)
    (area,) = m.areas
    assert area.tests == 1 and area.test_ids == 2 and area.classes == [] and m.coverage == []


def test_write_and_load(suite_map: SuiteMap, tmp_path: Path) -> None:
    folder = tmp_path / "map"
    (folder / "areas").mkdir(parents=True)
    (folder / "areas" / "gone.md").write_text("old", encoding="utf-8")
    written = write_map(suite_map, folder, max_coverage=2)
    assert len(written) == 3 + len(suite_map.areas)
    assert not (folder / "areas" / "gone.md").exists()  # an area that no longer exists
    assert "[rules](areas/rules.md)" in (folder / "overview.md").read_text(encoding="utf-8")
    rules_md = (folder / "areas" / "rules.md").read_text(encoding="utf-8")
    assert "base_setup(fresh_driver=False, policy_wait=True)" in rules_md
    assert "`settings`: 18 entries (seed)" in rules_md
    coverage = (folder / "coverage.md").read_text(encoding="utf-8")
    assert "more (see map.json)" in coverage  # only 2 listed
    loaded = load_map(folder)
    assert loaded is not None and loaded.areas == suite_map.areas
    assert load_map(tmp_path / "nowhere") is None


def test_cli_map(tmp_path: Path) -> None:
    out = tmp_path / "out"
    env = {"T2T_PATHS__CACHE_DIR": str(tmp_path / "cache")}
    first = CliRunner().invoke(app, ["map", str(STANDIN), "--out", str(out)], env=env)
    assert first.exit_code == 0, first.output
    assert "10 area(s), 90 tests" in first.output and "changed areas" not in first.output
    second = CliRunner().invoke(app, ["map", str(STANDIN), "--out", str(out)], env=env)
    assert "changed areas: none" in second.output  # same repo, same digests
    assert CliRunner().invoke(app, ["map", str(tmp_path / "missing")], env=env).exit_code == 2


def test_leftover_folders_and_imported_functions(tmp_path: Path) -> None:
    """Found on a real public suite: tests next to the domain folders got no area, and a
    method call named like an unrelated repo function was counted as that function."""
    repo = tmp_path / "repo"
    (repo / "tests" / "client").mkdir(parents=True)
    (repo / "lib").mkdir()
    (repo / "lib" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "lib" / "tools.py").write_text(
        "def get(url):\n    return url\n\n\ndef make_client():\n    return object()\n",
        encoding="utf-8",
    )
    (repo / "tests" / "client" / "test_client.py").write_text(
        "from lib.tools import make_client as build\n\n\ndef test_get():\n"
        "    client = build()\n    client.get('x')\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_root.py").write_text("def test_root():\n    pass\n", encoding="utf-8")
    settings = _settings(tmp_path)
    index, _, _ = update_index(repo, settings)
    m = build_map(index, settings)
    assert [(a.name, a.folders, a.tests) for a in m.areas] == [
        ("client", ["tests/client"], 1),
        ("tests", ["tests"], 1),  # only the files directly in tests/
    ]
    client = m.areas[0]
    assert [f.name for f in client.functions] == ["build"]  # imported under an alias
    assert "lib/tools.py" in client.sources
    assert m.overview.unassigned_tests == []


def test_an_area_lists_its_known_data_values(suite_map: SuiteMap, tmp_path: Path) -> None:
    """The suite's own values per key path: what a draft should pick from, and what a
    tracker-to-suite glossary maps onto."""
    files = _area(suite_map, "files")
    by_key = {v.key: v for v in files.data_values}
    assert {c.name for c in by_key["targets[].method"].values} == {"GET"}
    assert "block" in {c.name for c in by_key["policy.downloads.types.exe"].values}
    assert {"converted", "blocked"} <= {c.name for c in by_key["decision"].values}
    assert by_key["site.files[].name"].entries >= 1
    assert "test_id" not in by_key  # the id field is not a value
    write_map(suite_map, tmp_path, 10)
    text = (tmp_path / "areas" / "files.md").read_text(encoding="utf-8")
    assert "## Known data values" in text and "`decision`" in text


def test_values_that_nearly_all_differ_are_free_text(tmp_path: Path) -> None:
    from ticket2test.suitemap.build import known_values

    settings = _settings(tmp_path, map={"max_values_per_key": 3})
    entries = [{"test_id": f"t{i}", "name": f"rule-{i}", "mode": "proxy"} for i in range(10)]
    entries.append({"test_id": "t10", "name": "x" * 200, "mode": "isolate"})
    values = {v.key: v for v in known_values(entries, settings)}
    assert values["name"].free_text and values["name"].values == []
    assert values["name"].long_text == 1
    assert [(c.name, c.count) for c in values["mode"].values] == [("proxy", 10), ("isolate", 1)]
