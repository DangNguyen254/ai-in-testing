"""The usage table (index/usage.py) on the stand-in: each test's calls in order, a scope's
calls counted, and the framework's definitions, all by syntax with no model."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import Settings
from ticket2test.index.chunks import is_test_file
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.index.usage import render_scope, usage_table

STANDIN = REPO_ROOT / "standin"
FILE = "tests/rules/test_rules.py"
DELETE = f"{FILE}::TestRules.test_rules_delete_single"


def _settings(tmp_path: Path) -> Settings:
    return Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}})


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[IndexData, Settings]:
    settings = _settings(tmp_path_factory.mktemp("usage"))
    return update_index(STANDIN, settings)[0], settings


def test_a_tests_calls_are_kept_in_order_with_locals_read_as_their_chain(
    built: tuple[IndexData, Settings],
) -> None:
    index, settings = built
    table = usage_table(index, settings)
    assert table.sequences[DELETE] == [
        "nav.rules.list.open",  # ``rules = self.nav.rules.list`` then ``rules.open()``
        "nav.rules.list.select_rule",
        "nav.rules.list.delete_selected",
        "nav.rules.confirm.confirm",
        "nav.top_bar.save",
        "nav.top_bar.publish",
        "verify_targets",
    ]
    assert not any(c.startswith(("check.", "assert")) for s in table.sequences.values() for c in s)
    assert usage_table(index, settings) is table  # built once per index


def test_a_class_scope_counts_its_tests_calls_most_used_first(
    built: tuple[IndexData, Settings],
) -> None:
    index, settings = built
    table = usage_table(index, settings)
    uses = table.scope(index, file_path=FILE, class_name="TestRules")
    by_call = {u.call: u for u in uses}
    assert uses[0].call == "nav.rules.list.open" and uses[0].position < 0.1  # nearly always first
    verify = by_call["verify_targets"]
    assert verify.position > 0.66 and verify.defined_in == "ValidationMixin"
    assert by_call["nav.top_bar.publish"].defined_in == "TopBar"
    assert [u.tests for u in uses] == sorted((u.tests for u in uses), reverse=True)
    without = table.scope(index, file_path=FILE, class_name="TestRules", exclude={DELETE})
    assert {u.call: u.tests for u in without}["nav.rules.confirm.confirm"] == (
        by_call["nav.rules.confirm.confirm"].tests - 1
    )
    folder = table.scope(index, folder="tests/rules")
    assert {u.call for u in uses} <= {u.call for u in folder}

    text = render_scope(uses, 3)
    first = text.splitlines()[0]
    assert first.startswith("U1: `self.nav.rules.list.open` used by ")
    assert "usually at the start" in first and "e.g. `rules.open()`" in first
    assert text.splitlines()[-1].startswith(f"... {len(uses) - 3} more call(s)")


def test_the_frameworks_definitions_cover_what_no_test_calls(
    built: tuple[IndexData, Settings],
) -> None:
    index, settings = built
    table = usage_table(index, settings)
    verify = next(d for d in table.definitions if d.name == "verify_targets")
    assert (verify.owner, verify.signature, verify.file_path) == (
        "ValidationMixin",
        "(self)",
        "framework/validations.py",
    )
    assert "_check" in verify.calls
    assert all(d.signature != "(...)" for d in table.definitions)  # every one parsed
    # no test file, but an area's helper module next to the tests is in (a class's helpers)
    assert not any(is_test_file(d.file_path, settings.index) for d in table.definitions)
    assert any(d.file_path.startswith("tests/") and d.owner for d in table.definitions)
    called = {c.removesuffix("()").rpartition(".")[2] for s in table.sequences.values() for c in s}
    assert any(d.owner and d.name not in called for d in table.definitions)


def test_picks_are_taken_by_label_and_unknown_labels_dropped(
    built: tuple[IndexData, Settings],
) -> None:
    import json

    from tests.test_generate import _draft
    from ticket2test.generate.pick import pick_rows, table_rows
    from ticket2test.llm import FakeLLMClient

    index, settings = built
    rows = table_rows(index, settings, FILE, "TestRules", exclude={DELETE})
    labels = {u.call: f"U{n}" for n, u in enumerate(rows, 1)}
    reply = {
        "picks": [
            {"line": "S2", "rows": [labels["nav.rules.list.delete_selected"], "U999"]},
            {"line": "e", "rows": [labels["verify_targets"]]},
            {"line": "S9", "rows": ["U1"]},
        ]
    }
    fake = FakeLLMClient([json.dumps(reply)])
    picked, dropped, calls = pick_rows(_draft(), rows, "TestRules", settings, fake)
    assert picked == {"S2": ["nav.rules.list.delete_selected"], "E": ["verify_targets"]}
    assert (dropped, calls) == (2, 1)  # U999 not shown, S9 not a draft line
    asked = fake.requests[0].messages[1].content
    assert "S2. Delete and confirm" in asked and "U1: `self." in asked
    assert rows[0].call in {
        u.call
        for u in usage_table(index, settings).scope(index, file_path=FILE, class_name="TestRules")
    }
