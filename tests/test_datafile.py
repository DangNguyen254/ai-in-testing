"""Data-file shapes from real suites: a defaults row, and data files per test function."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import DataSettings, IndexSettings, Settings
from ticket2test.index.datafile import layout_of, merged, split_defaults
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.validate.suite import check_suite

STANDIN = REPO_ROOT / "standin"
RULES = "tests/rules/test_rules"
OWN_FILE_TEST = "test_rules_list_search"


def test_split_and_merge() -> None:
    data = DataSettings()
    defaults, rows = split_defaults([{"a": 1}, {"test_id": "t", "b": 2}], data)
    assert defaults == {"a": 1} and rows == [{"test_id": "t", "b": 2}]
    assert split_defaults([{"test_id": "t"}, {"a": 1}], data) == (
        None,
        [{"test_id": "t"}, {"a": 1}],
    )
    off = DataSettings(defaults_row=False)
    assert split_defaults([{"a": 1}], off) == (None, [{"a": 1}])
    base = {"settings": {"x": 1, "y": 1}, "policy": {}}
    entry = {"test_id": "t", "settings": {"y": 2}}
    assert merged(entry, base, data) == {"settings": {"y": 2}, "policy": {}, "test_id": "t"}
    deep = DataSettings(defaults_merge="deep")
    assert merged(entry, base, deep)["settings"] == {"x": 1, "y": 2}
    assert merged(entry, None, data) is entry


def test_layout_of() -> None:
    cfg = IndexSettings()
    assert layout_of("a/test_m.py", "test_f", "a/test_f.json", cfg) == "function"
    assert layout_of("a/test_m.py", "test_f", "a/test_m.json", cfg) == "module"
    assert layout_of("a/test_m.py", "test_f", None, cfg) == "module"


def _real_shapes(dest: Path) -> dict[str, Any]:
    """The stand-in with a defaults row in the rules data file (the shared settings block
    moved into it) and one rules test given a data file of its own."""
    shutil.copytree(STANDIN, dest, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    path = dest / f"{RULES}.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    shared = rows[0]["settings"]
    mine = lambda row: row["test_id"].split("[")[0] == OWN_FILE_TEST  # noqa: E731
    own = [r for r in rows if mine(r)]
    rest = [r for r in rows if not mine(r)]
    assert own, "the stand-in test chosen for its own file has entries"
    for row in rest:
        if row.get("settings") == shared:
            del row["settings"]
    path.write_text(json.dumps([{"settings": shared}, *rest], indent=3), encoding="utf-8")
    (dest / f"tests/rules/{OWN_FILE_TEST}.json").write_text(json.dumps(own, indent=3), "utf-8")
    return shared  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def shaped(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Settings, IndexData, Any]:
    folder = tmp_path_factory.mktemp("shapes")
    repo = folder / "repo"
    shared = _real_shapes(repo)
    settings = Settings.model_validate({"paths": {"cache_dir": str(folder / "cache")}})
    index, _, _ = update_index(repo, settings)
    return repo, settings, index, shared


def test_the_index_reads_both_shapes(shaped: tuple[Path, Settings, IndexData, Any]) -> None:
    _, _, index, shared = shaped
    rules = [c for c in index.chunks if c.kind == "test" and c.file_path == f"{RULES}.py"]
    add = next(c for c in rules if c.symbol_name == "test_rules_add_basic")
    assert add.data_defaults == {"settings": shared}
    assert all("settings" not in e for e in add.data_entries.values())  # own keys only
    own = next(c for c in rules if c.symbol_name == OWN_FILE_TEST)
    assert own.data_file == f"tests/rules/{OWN_FILE_TEST}.json"
    assert own.data_entries and set(own.data_entries) == set(own.test_ids)
    assert own.data_defaults == {}


def test_the_suite_check_stays_clean(shaped: tuple[Path, Settings, IndexData, Any]) -> None:
    """Without the two shapes, every rules test would read keys its entry 'lacks' (they are in
    the defaults row), and the per-function test would have 'no entry'."""
    repo, settings, _, _ = shaped
    report = check_suite(repo, settings)
    assert report.errors == 0, [(c.check, c.examples) for c in report.by_check]


def test_without_the_two_shapes_the_check_fails(
    shaped: tuple[Path, Settings, IndexData, Any], tmp_path: Path
) -> None:
    repo, _, _, _ = shaped
    off = Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "data": {"defaults_row": False},
            "index": {"function_data_files": False},
        }
    )
    report = check_suite(repo, off)
    checks = {c.check for c in report.by_check}
    assert report.errors > 0 and {"ids"} <= checks, checks
