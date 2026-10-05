"""Checks the synthetic stand-in suite against the Phase 3 definition of done.

The stand-in is hand-written, trusted project code, so collecting it on the host is allowed
(Hard Constraint 3 covers generated tests only).
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.config import Settings
from ticket2test.normalize import normalize

STANDIN = REPO_ROOT / "standin"
MANIFEST = json.loads((STANDIN / "manifest.json").read_text(encoding="utf-8"))

# Collects in a subprocess and prints one JSON line per test with its final markers.
_PROBE = r"""
import json, pytest

class Probe:
    def pytest_collection_finish(self, session):
        for item in session.items:
            skips = []
            for m in item.iter_markers():
                if m.name == "skip" or (m.name == "skipif" and m.args and m.args[0]):
                    skips.append(m.kwargs.get("reason", ""))
            print("ITEM " + json.dumps({
                "nodeid": item.nodeid,
                "file": item.nodeid.split("::")[0],
                "name": item.name,
                "function": item.nodeid.split("[")[0],
                "markers": {m.name: list(m.args) for m in item.iter_markers()
                            if m.name in ("priority", "project", "component", "suite")},
                "priority": item.get_closest_marker("priority").args[0],
                "skips": skips,
            }))

raise SystemExit(pytest.main(["--collect-only", "-q"], plugins=[Probe()]))
"""


def _collect(deployment: str) -> list[dict[str, Any]]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("STANDIN_")}
    env["STANDIN_DEPLOYMENT"] = deployment
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=STANDIN,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line[5:]) for line in result.stdout.splitlines() if line.startswith("ITEM ")]


@pytest.fixture(scope="module")
def items() -> list[dict[str, Any]]:
    return _collect("cloud")


@pytest.fixture(scope="module")
def on_prem_items() -> list[dict[str, Any]]:
    return _collect("on_prem")


def _data(test_file: str) -> dict[str, Any]:
    path = STANDIN / Path(test_file).with_suffix(".json")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


# --- Collection and data files ----------------------------------------------------------


def test_collects_without_browser_or_network(items: list[dict[str, Any]]) -> None:
    assert len(items) >= 20


def test_json_keys_exactly_match_collected_test_ids(items: list[dict[str, Any]]) -> None:
    by_file: dict[str, set[str]] = {}
    for item in items:
        by_file.setdefault(item["file"], set()).add(item["name"])
    assert len(by_file) >= 4
    for test_file, names in by_file.items():
        assert set(_data(test_file)) == names, test_file


def test_every_test_file_has_a_data_file() -> None:
    for test_file in (STANDIN / "tests").rglob("test_*.py"):
        assert test_file.with_suffix(".json").is_file(), test_file


def test_stacked_parametrize_ids_put_the_bottom_decorator_first(
    items: list[dict[str, Any]],
) -> None:
    names = {i["name"] for i in items}
    # @parametrize("entry_mode", ...) above @parametrize("quantity", ...): quantity comes first.
    assert "test_create_item_rejects_invalid_quantity[0-typed]" in names
    assert "test_create_item_rejects_invalid_quantity[typed-0]" not in names
    assert "test_create_item_rejects_invalid_quantity[0-typed]" in _data(
        "tests/inventory/test_inventory.py"
    )


def test_all_tests_carry_the_four_markers_with_known_values(items: list[dict[str, Any]]) -> None:
    markers = Settings().markers
    for item in items:
        m = item["markers"]
        assert set(m) == {"priority", "project", "component", "suite"}, item["nodeid"]
        assert item["priority"] in markers.priorities
        assert m["project"] == [markers.project]
        assert m["suite"][0] in markers.suites


def test_tests_use_the_base_class() -> None:
    for test_file in (STANDIN / "tests").rglob("test_*.py"):
        assert re.search(r"^class Test\w+\(BaseTest\):", test_file.read_text("utf-8"), re.M)


# --- Overrides and skips ----------------------------------------------------------------


def test_entry_priority_override_is_applied(items: list[dict[str, Any]]) -> None:
    by_name = {i["name"]: i for i in items}
    assert by_name["test_create_item[1]"]["priority"] == "p1"  # from the decorator
    assert by_name["test_create_item[50]"]["priority"] == "p2"  # from the JSON entry


def test_entry_skip_cites_a_ticket_id(items: list[dict[str, Any]]) -> None:
    pattern = re.compile(Settings().eval.ticket_id_pattern)
    skipped = [i for i in items if any(pattern.search(r) for r in i["skips"])]
    assert [i["name"] for i in skipped] == ["test_enable_weekly_digest"]
    assert skipped[0]["skips"][0].startswith("STND-105:")


def test_deployment_type_skips(
    items: list[dict[str, Any]], on_prem_items: list[dict[str, Any]]
) -> None:
    def skipped(collected: list[dict[str, Any]]) -> set[str]:
        return {i["name"] for i in collected if any("only test" in r for r in i["skips"])}

    assert skipped(items) == {"test_deactivate_user"}
    assert skipped(on_prem_items) == {"test_sso_banner_on_user_list"}


def test_unique_names_use_the_placeholder() -> None:
    for data_file in (STANDIN / "tests").rglob("test_*.json"):
        for name, entry in json.loads(data_file.read_text("utf-8")).items():
            for key in ("name", "email"):
                value = entry["inputs"].get(key)
                if value is not None:
                    assert "{{unique}}" in value, f"{data_file.name}:{name} {key}={value}"


def test_entries_repeat_a_large_config_block() -> None:
    data = _data("tests/orders/test_orders.py")
    blocks = [json.dumps(entry["config"], sort_keys=True) for entry in data.values()]
    assert len(set(blocks)) == 1
    assert len(blocks[0]) > 400


# --- Test kinds (manifest) --------------------------------------------------------------


def test_manifest_covers_exactly_the_collected_functions(items: list[dict[str, Any]]) -> None:
    assert set(MANIFEST["tests"]) == {i["function"] for i in items}


def test_test_kind_mix() -> None:
    kinds = Counter(t["kind"] for t in MANIFEST["tests"].values())
    total = sum(kinds.values())
    assert total >= 20
    assert 0.80 <= kinds["ui"] / total <= 0.92
    assert kinds["api"] >= 1
    assert kinds["hybrid"] >= 1


def test_api_tests_never_touch_the_browser() -> None:
    for function, info in MANIFEST["tests"].items():
        if info["kind"] != "api":
            continue
        path, _, name = function.split("::")
        source = (STANDIN / path).read_text("utf-8")
        body = source.split(f"def {name}(", 1)[1].split("\n    @", 1)[0]
        assert "self.nav" not in body and "self.driver" not in body, function


# --- Tickets ----------------------------------------------------------------------------


def test_fake_tickets_normalize_and_map_to_tests() -> None:
    source = JiraExportSource(STANDIN / "tickets" / "export.json")
    assert len(MANIFEST["tickets"]) >= 5
    for key, info in MANIFEST["tickets"].items():
        ticket = normalize(source.fetch(key))
        assert ticket.steps_to_reproduce and ticket.expected, key
        for function in info["tests"]:
            assert function in MANIFEST["tests"], (key, function)


# --- Git history ------------------------------------------------------------------------


def test_history_has_skip_removed_by_fix_commits(tmp_path: Path) -> None:
    sys.path.insert(0, str(STANDIN / "tools"))
    try:
        build_history = importlib.import_module("build_history")
    finally:
        sys.path.remove(str(STANDIN / "tools"))
    repo = build_history.build(tmp_path / "history")

    def git(*args: str) -> str:
        out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
        return out.stdout

    subjects = git("log", "--reverse", "--format=%s").splitlines()
    assert subjects == [
        "Add stand-in suite",
        "Fix STND-103: reject item quantities below 1",
        "Fix STND-104: cancelling an order sets it to cancelled",
    ]
    pattern = re.compile(Settings().eval.ticket_id_pattern)
    for rev, ticket in (("HEAD~1", "STND-103"), ("HEAD", "STND-104")):
        removed = [
            line
            for line in git("show", "--format=", rev, "--", "tests").splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
        assert any(ticket in pattern.findall(line) for line in removed), rev
    # The final tree is the stand-in as committed.
    assert "skip" not in _data("tests/orders/test_orders.py")["test_cancel_order"]


# --- App state (no server needed) -------------------------------------------------------


@pytest.fixture
def state_module() -> Iterator[ModuleType]:
    sys.path.insert(0, str(STANDIN))
    try:
        yield importlib.import_module("app.state")
    finally:
        sys.path.remove(str(STANDIN))


def test_app_state_rules(state_module: ModuleType) -> None:
    store = state_module.Store()
    store.seed({"items": [{"name": "widget", "quantity": 5}]})
    with pytest.raises(state_module.ValidationError, match="at least 1"):
        store.create_item("bad", 0)
    order = store.create_order([{"item": "widget", "quantity": 2}])
    assert store.items["widget"]["quantity"] == 3
    store.cancel_order(order["id"])
    assert order["status"] == "cancelled"
    assert store.items["widget"]["quantity"] == 5
    # STND-105 is a deliberate open bug: the weekly digest is not saved.
    store.update_settings({"notifications": {"weekly_digest": True}})
    assert store.settings["notifications"]["weekly_digest"] is False


# --- Generic names only -----------------------------------------------------------------


def test_only_generic_hosts_in_the_standin() -> None:
    allowed = {"localhost", "127.0.0.1", "example.com", "jira.example.com"}
    host = re.compile(r"https?://([A-Za-z0-9.-]+)")
    # "@" right after a name character (or the closing "}}" of a placeholder), not a decorator.
    email_domain = re.compile(r"(?<=[\w}])@([A-Za-z0-9-]+\.[A-Za-z0-9.-]+)")
    for path in STANDIN.rglob("*"):
        if path.suffix not in {".py", ".json", ".md", ".ini"} or "__pycache__" in path.parts:
            continue
        text = path.read_text("utf-8")
        for found in host.findall(text) + email_domain.findall(text):
            assert found in allowed, f"{path.relative_to(STANDIN)}: {found}"
