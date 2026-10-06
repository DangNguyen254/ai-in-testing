"""Checks the synthetic stand-in suite against the Phase 3 / 3b definition of done.

The stand-in is hand-written, trusted project code, so collecting it on the host is allowed
(Hard Constraint 3 covers generated tests only). Source checks use the ``ast`` module.
"""

from __future__ import annotations

import ast
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
TEST_FILES = sorted((STANDIN / "tests").rglob("test_*.py"))
FRAMEWORK_KEYS = {"settings", "policy", "tenants", "targets", "interactions", "priority", "skip"}
SEED_SECTIONS = ("settings", "policy", "tenants", "targets")
CLASS_DECORATORS = ("browsers", "environments", "pytest.mark.project", "pytest.mark.component")

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


def _collect(deployment: str, browser: str = "chrome") -> list[dict[str, Any]]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("STANDIN_")}
    env.update(STANDIN_DEPLOYMENT=deployment, STANDIN_BROWSER=browser)
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


def _entries(test_file: str | Path) -> list[dict[str, Any]]:
    path = STANDIN / Path(test_file).with_suffix(".json")
    entries: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return entries


def _by_id(test_file: str | Path) -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in _entries(test_file)}


def _all_entries() -> list[dict[str, Any]]:
    return [entry for path in TEST_FILES for entry in _entries(path)]


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else ""


def _test_classes() -> Iterator[tuple[Path, ast.ClassDef]]:
    for path in TEST_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                yield path, node


def _test_functions() -> Iterator[tuple[Path, ast.ClassDef, ast.FunctionDef]]:
    for path, cls in _test_classes():
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                yield path, cls, node


def _reads_params(function: ast.FunctionDef) -> set[str]:
    """Keys a test body reads from its entry: ``self.params["k"]`` or ``params["k"]``."""
    keys = set()
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Subscript)
            and _dotted(node.value) in ("self.params", "params")
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def _uses_params(function: ast.FunctionDef) -> bool:
    return bool(_reads_params(function)) or any(
        isinstance(node, ast.Call) and _dotted(node.func) == "self.validate_backend"
        for node in ast.walk(function)
    )


# --- Collection and data files ----------------------------------------------------------


def test_collects_without_browser_or_network(items: list[dict[str, Any]]) -> None:
    assert len(items) >= 30
    assert len({i["file"] for i in items}) >= 4


def test_entry_ids_are_collected_test_ids(items: list[dict[str, Any]]) -> None:
    names: dict[str, set[str]] = {}
    for item in items:
        names.setdefault(item["file"], set()).add(item["name"])
    for test_file, collected in names.items():
        ids = [entry["id"] for entry in _entries(test_file)]
        assert len(ids) == len(set(ids)), f"duplicate ids in {test_file}"
        assert set(ids) <= collected, set(ids) - collected


def test_tests_that_use_params_have_an_entry_per_variant(items: list[dict[str, Any]]) -> None:
    collected = {(i["file"], i["name"].split("[")[0]): set() for i in items}
    for i in items:
        collected[(i["file"], i["name"].split("[")[0])].add(i["name"])
    without_entry = set()
    for path, _cls, function in _test_functions():
        rel = path.relative_to(STANDIN).as_posix()
        variants = collected[(rel, function.name)]
        ids = set(_by_id(path))
        if _uses_params(function):
            assert variants <= ids, (function.name, variants - ids)
        elif not variants & ids:
            without_entry.add(function.name)
    # Tests that read no data may have no entry.
    assert without_entry == {"test_inventory_items_list_empty", "test_users_list_sso_banner"}


def test_every_data_key_a_test_reads_exists_in_its_entries() -> None:
    for path, _cls, function in _test_functions():
        keys = _reads_params(function)
        entries = [e for e in _entries(path) if e["id"].split("[")[0] == function.name]
        for entry in entries:
            assert keys <= set(entry), (entry["id"], keys - set(entry))


def test_data_files_are_arrays_with_framework_and_custom_keys() -> None:
    custom = set()
    for path in TEST_FILES:
        entries = _entries(path)
        assert isinstance(entries, list) and entries, path
        for entry in entries:
            assert isinstance(entry["id"], str)
            custom |= set(entry) - FRAMEWORK_KEYS - {"id"}
            for interaction in entry.get("interactions", []):
                assert set(interaction) == {"request", "response"}
                assert {"method", "endpoint"} <= set(interaction["request"])
                assert "status" in interaction["response"]
    assert {"item_name", "email", "expected_items", "count"} <= custom


def test_stacked_parametrize_ids_put_the_bottom_decorator_first(
    items: list[dict[str, Any]],
) -> None:
    names = {i["name"] for i in items}
    # @parametrize("entry_mode", ...) above @parametrize("quantity", ...): quantity comes first.
    assert "test_inventory_item_create_invalid_quantity[0-typed]" in names
    assert "test_inventory_item_create_invalid_quantity[typed-0]" not in names
    assert "test_inventory_item_create_invalid_quantity[0-typed]" in _by_id(
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


# --- Class scaffold, page objects, assertions -------------------------------------------


def test_classes_use_the_base_class_and_the_decorator_stack() -> None:
    styles = Counter()
    for _path, cls in _test_classes():
        assert [_dotted(b) for b in cls.bases] == ["BaseTest"], cls.name
        decorators = [_dotted(d) for d in cls.decorator_list]
        assert [d for d in decorators if d != "data_driven"] == list(CLASS_DECORATORS), cls.name
        styles["self.params" if "data_driven" in decorators else "params argument"] += 1
    # Most classes load data with the class decorator; some take a ``params`` argument.
    assert styles["self.params"] >= 2 and styles["params argument"] >= 1


def test_params_argument_classes_take_params_in_every_test() -> None:
    for _path, cls, function in _test_functions():
        decorators = [_dotted(d) for d in cls.decorator_list]
        args = [a.arg for a in function.args.args]
        if "data_driven" in decorators:
            assert "params" not in args, function.name
        elif _uses_params(function):
            assert "params" in args, function.name


def test_page_objects_use_properties_and_never_chain() -> None:
    setters = 0
    for path in (STANDIN / "framework" / "pages").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef):
                decorators = [_dotted(d) for d in node.decorator_list]
                setters += any(d.endswith(".setter") for d in decorators)
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
                assert node.value.id != "self", path.name  # actions return nothing
    assert setters >= 10
    for path, _cls, function in _test_functions():
        for statement in function.body:
            for node in ast.walk(statement):
                # No ``page.open().x``: a call's result is never used as an object.
                is_chained = isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call)
                assert not is_chained, (path.name, function.name)


def test_ui_checks_use_the_assertion_object() -> None:
    for path, _cls, function in _test_functions():
        assert not any(isinstance(n, ast.Assert) for n in ast.walk(function)), function.name
        calls = {_dotted(n.func) for n in ast.walk(function) if isinstance(n, ast.Call)}
        assert calls & {"self.check.equal", "self.check.same_items", "self.validate_backend"}, (
            path.name,
            function.name,
        )


def test_test_names_summarize_area_and_never_contain_ticket_ids() -> None:
    pattern = re.compile(Settings().eval.ticket_id_pattern)
    for path, cls, function in _test_functions():
        area = path.stem.removeprefix("test_")
        assert function.name.startswith(f"test_{area}_"), function.name
        assert len(function.name.split("_")) >= 4, function.name
        assert not pattern.search(function.name) and not re.search(r"\d{3,}", function.name)
        assert not re.search(r"\d{3,}", cls.name)


# --- Repetition, placeholders, self-referencing names ------------------------------------


def test_large_seed_blocks_repeat_across_entries() -> None:
    for test_file in ("tests/inventory/test_inventory.py", "tests/orders/test_orders.py"):
        entries = _entries(test_file)
        settings = {json.dumps(e["settings"], sort_keys=True) for e in entries}
        assert len(settings) == 1
        policies = [{k: v for k, v in e["policy"].items() if k != "name"} for e in entries]
        common = Counter(json.dumps(p, sort_keys=True) for p in policies).most_common(1)[0]
        assert common[1] >= len(entries) - 3 and len(common[0]) > 600


def test_variants_differ_by_one_or_two_values() -> None:
    entries = _by_id("tests/inventory/test_inventory.py")
    one = entries["test_inventory_item_create_category_not_allowed[software]"]
    other = entries["test_inventory_item_create_category_not_allowed[office]"]
    assert {k: v for k, v in one.items() if k != "id"} == {
        k: v for k, v in other.items() if k != "id"
    }
    small, big = entries["test_inventory_item_create[1]"], entries["test_inventory_item_create[50]"]
    assert set(big) - set(small) == {"priority"}
    assert small["policy"] == big["policy"]


def test_policy_names_derive_from_the_test_name() -> None:
    for entry in _all_entries():
        if "policy" in entry:
            function = entry["id"].split("[")[0].removeprefix("test_")
            assert entry["policy"]["name"] == "policy-" + function.replace("_", "-")


def test_unique_names_use_the_placeholder() -> None:
    for entry in _all_entries():
        for key in ("item_name", "email"):
            if key in entry:
                assert "{{unique}}" in entry[key], (entry["id"], key)
        for item in entry.get("targets", {}).get("items", []):
            assert "{{unique}}" in item["name"], entry["id"]


# --- Style -------------------------------------------------------------------------------


def test_python_style_is_clean_per_the_standin_ruff_config() -> None:
    config = str(STANDIN / "ruff.toml")
    for command in (["format", "--check"], ["check"]):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", *command, "--no-cache", "--config", config, "."],
            cwd=STANDIN,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_python_has_no_type_annotations_and_uses_lf() -> None:
    for path in STANDIN.rglob("*.py"):
        raw = path.read_bytes()
        assert b"\r\n" not in raw and raw.endswith(b"\n"), path
        for node in ast.walk(ast.parse(raw)):
            assert not isinstance(node, ast.AnnAssign), path
            if isinstance(node, ast.FunctionDef):
                assert node.returns is None, (path, node.name)
                args = node.args.args + node.args.kwonlyargs + node.args.posonlyargs
                assert all(a.annotation is None for a in args), (path, node.name)


def test_json_style_indent_3_compact_keys_final_newline() -> None:
    for path in (STANDIN / "tests").rglob("*.json"):
        raw = path.read_bytes().decode("utf-8")
        formatted = json.dumps(json.loads(raw), indent=3, separators=(",", ":"), ensure_ascii=False)
        assert raw == formatted + "\n", path


# --- Overrides and skips ----------------------------------------------------------------


def test_entry_priority_override_is_applied(items: list[dict[str, Any]]) -> None:
    by_name = {i["name"]: i for i in items}
    assert by_name["test_inventory_item_create[1]"]["priority"] == "p1"  # from the decorator
    assert by_name["test_inventory_item_create[50]"]["priority"] == "p2"  # from the JSON entry


def test_entry_skip_cites_a_ticket_id(items: list[dict[str, Any]]) -> None:
    pattern = re.compile(Settings().eval.ticket_id_pattern)
    skipped = [i for i in items if any(pattern.search(r) for r in i["skips"])]
    assert [i["name"] for i in skipped] == ["test_settings_notifications_digest_enable"]
    assert skipped[0]["skips"][0].startswith("STND-105:")


def test_deployment_type_skips(
    items: list[dict[str, Any]], on_prem_items: list[dict[str, Any]]
) -> None:
    def skipped(collected: list[dict[str, Any]]) -> set[str]:
        return {i["name"] for i in collected if any("only test" in r for r in i["skips"])}

    assert skipped(items) == {"test_users_profile_deactivate"}
    assert skipped(on_prem_items) == {"test_users_list_sso_banner"}


def test_platform_selection_skips_other_browsers() -> None:
    collected = _collect("cloud", browser="safari")
    assert collected and all(any("runs only on" in r for r in i["skips"]) for i in collected)


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
    kinds = {f.split("::")[-1]: info["kind"] for f, info in MANIFEST["tests"].items()}
    for _path, _cls, function in _test_functions():
        if kinds[function.name] != "api":
            continue
        used = {_dotted(n) for n in ast.walk(function) if isinstance(n, ast.Attribute)}
        assert not any(u.startswith(("self.nav", "self.driver")) for u in used), function.name


# --- Interactions replay against the app (in process, no server) -------------------------


@pytest.fixture
def standin_modules() -> Iterator[dict[str, ModuleType]]:
    sys.path.insert(0, str(STANDIN))
    try:
        yield {
            "state": importlib.import_module("app.state"),
            "server": importlib.import_module("app.server"),
            "names": importlib.import_module("framework.names"),
            "validations": importlib.import_module("framework.validations"),
        }
    finally:
        sys.path.remove(str(STANDIN))


def _replay(modules: dict[str, ModuleType], entry: dict[str, Any], action: Any = None) -> None:
    """Seed the app from the entry, run the UI action's backend effect, replay interactions."""
    server, validations = modules["server"], modules["validations"]
    entry = modules["names"].resolve_placeholders(entry, "abc123")
    store = server.STORE
    store.reset()
    store.seed({k: entry[k] for k in SEED_SECTIONS if k in entry})
    if action:
        action(store, entry)
    for interaction in entry.get("interactions", []):
        request, expected = interaction["request"], interaction["response"]
        parts = [p for p in request["endpoint"].strip("/").split("/") if p]
        try:
            status, body = 200, server.route_api(request["method"], parts, request.get("body"))
        except modules["state"].ValidationError as error:
            status, body = 422, {"error": str(error)}
        except (KeyError, LookupError, ValueError):
            status, body = 404, {"error": "not found"}
        assert status == expected["status"], (entry["id"], request)
        if "body" in expected:
            validations.matches_subset(body, expected["body"])


# The backend effect of each UI flow, so expectations can be checked without a browser.
_UI_EFFECTS: dict[str, Any] = {
    "test_inventory_item_create[1]": lambda s, e: s.create_item(e["item_name"], 1, "hardware"),
    "test_inventory_item_create[50]": lambda s, e: s.create_item(e["item_name"], 50, "hardware"),
    "test_inventory_item_edit_category": lambda s, e: s.update_item(
        e["item_name"], category="office"
    ),
    "test_inventory_item_delete": lambda s, e: s.delete_item(e["item_name"]),
    "test_orders_checkout_place": lambda s, e: s.create_order(
        [{"item": e["item_name"], "quantity": 3}]
    ),
    "test_orders_detail_cancel": lambda s, e: s.cancel_order(1),
    "test_orders_api_create_cancel_in_ui": lambda s, e: s.cancel_order(
        s.create_order([{"item": e["item_name"], "quantity": 1}])["id"]
    ),
    "test_settings_general_timezone_reload": lambda s, e: s.update_settings(
        {"timezone": "America/New_York"}
    ),
    "test_users_profile_role_change": lambda s, e: s.change_role(e["email"], "admin"),
}


@pytest.mark.parametrize(
    "test_file, entry_id",
    [
        ("tests/inventory/test_inventory.py", "test_inventory_items_api_list"),
        ("tests/orders/test_orders.py", "test_orders_api_create_unknown_item"),
        (
            "tests/inventory/test_inventory.py",
            "test_inventory_item_create_invalid_quantity[0-typed]",
        ),
    ],
)
def test_interactions_replay(
    standin_modules: dict[str, ModuleType], test_file: str, entry_id: str
) -> None:
    _replay(standin_modules, _by_id(test_file)[entry_id])


def test_ui_flow_interactions_replay(standin_modules: dict[str, ModuleType]) -> None:
    entries = {e["id"]: e for e in _all_entries()}
    for entry_id, action in _UI_EFFECTS.items():
        _replay(standin_modules, entries[entry_id], action)


def test_policy_limit_is_enforced(standin_modules: dict[str, ModuleType]) -> None:
    entry = _by_id("tests/orders/test_orders.py")["test_orders_checkout_policy_limit"]
    state = standin_modules["state"]
    with pytest.raises(state.ValidationError, match=re.escape(entry["error"])):
        _replay(
            standin_modules,
            entry,
            lambda s, e: s.create_order([{"item": e["item_name"], "quantity": e["quantity"]}]),
        )


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
    assert "skip" not in _by_id("tests/orders/test_orders.py")["test_orders_detail_cancel"]


# --- App state (no server needed) -------------------------------------------------------


def test_app_state_rules(standin_modules: dict[str, ModuleType]) -> None:
    state = standin_modules["state"]
    store = state.Store()
    store.seed({"targets": {"items": [{"name": "widget", "quantity": 5}]}})
    with pytest.raises(state.ValidationError, match="at least 1"):
        store.create_item("bad", 0)
    order = store.create_order([{"item": "widget", "quantity": 2}])
    assert store.items["widget"]["quantity"] == 3
    store.cancel_order(order["id"])
    assert order["status"] == "cancelled"
    assert store.items["widget"]["quantity"] == 5
    store.seed({"policy": {"allowed_categories": ["general"]}})
    with pytest.raises(state.ValidationError, match="not allowed by policy"):
        store.create_item("tool", 1, "hardware")
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
        if path.suffix not in {".py", ".json", ".md", ".ini", ".toml"}:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text("utf-8")
        for found in host.findall(text) + email_domain.findall(text):
            assert found in allowed, f"{path.relative_to(STANDIN)}: {found}"
