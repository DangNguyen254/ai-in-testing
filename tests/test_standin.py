"""Checks the synthetic stand-in suite against the Phase 3 / 3b definition of done (v3).

The stand-in is hand-written, trusted project code, so collecting it on the host is allowed
(Hard Constraint 3 covers generated tests only). Source checks use the ``ast`` module;
expectations are replayed in-process against the app's state and API router (no server).
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
from collections.abc import Callable, Iterator
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
ID = "test_id"
SEED = {"settings", "policy", "tenants"}
EXPECTATIONS = {"targets": "self.verify_targets", "interactions": "self.verify_interactions"}
OVERRIDES = {"priority", "skip"}
SUFFIX = "abc123"

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
    return {entry[ID]: entry for entry in _entries(test_file)}


def _all_entries() -> dict[str, dict[str, Any]]:
    return {entry[ID]: entry for path in TEST_FILES for entry in _entries(path)}


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else ""


def _test_classes() -> Iterator[tuple[Path, ast.ClassDef]]:
    for path in TEST_FILES:
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                yield path, node


def _test_functions() -> Iterator[tuple[Path, ast.ClassDef, ast.FunctionDef]]:
    for path, cls in _test_classes():
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                yield path, cls, node


def _functions() -> dict[str, tuple[Path, ast.ClassDef, ast.FunctionDef]]:
    return {function.name: (path, cls, function) for path, cls, function in _test_functions()}


def _calls(function: ast.FunctionDef) -> set[str]:
    return {_dotted(n.func) for n in ast.walk(function) if isinstance(n, ast.Call)}


def _reads(function: ast.FunctionDef) -> set[str]:
    """Keys a test body reads from its entry: ``self.params["k"]`` or ``params["k"]``."""
    return {
        node.slice.value
        for node in ast.walk(function)
        if isinstance(node, ast.Subscript)
        and _dotted(node.value) in ("self.params", "params")
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }


def _uses_entry(function: ast.FunctionDef) -> bool:
    return bool(_reads(function)) or bool(_calls(function) & set(EXPECTATIONS.values()))


# --- Collection and data files ----------------------------------------------------------


def test_collects_without_browser_or_network(items: list[dict[str, Any]]) -> None:
    assert len(items) >= 30
    assert len({i["file"] for i in items}) == 5


def test_entry_ids_are_collected_test_ids(items: list[dict[str, Any]]) -> None:
    names: dict[str, set[str]] = {}
    for item in items:
        names.setdefault(item["file"], set()).add(item["name"])
    for test_file, collected in names.items():
        ids = [entry[ID] for entry in _entries(test_file)]
        assert len(ids) == len(set(ids)), f"duplicate ids in {test_file}"
        assert set(ids) <= collected, set(ids) - collected


def test_tests_that_use_their_entry_have_one_per_variant(items: list[dict[str, Any]]) -> None:
    variants: dict[str, set[str]] = {}
    for item in items:
        variants.setdefault(item["name"].split("[")[0], set()).add(item["name"])
    entries = _all_entries()
    without_entry = set()
    for name, (_path, _cls, function) in _functions().items():
        if _uses_entry(function):
            assert variants[name] <= set(entries), (name, variants[name] - set(entries))
        elif not variants[name] & set(entries):
            without_entry.add(name)
    assert without_entry == {"test_rules_list_empty", "test_profiles_list_empty"}


def test_every_entry_key_is_read_or_consumed() -> None:
    """Custom keys are read by the test; an expectation section only with its helper."""
    functions = _functions()
    for entry_id, entry in _all_entries().items():
        function = functions[entry_id.split("[")[0]][2]
        reads, calls = _reads(function), _calls(function)
        assert reads <= set(entry), (entry_id, reads - set(entry))
        for key in set(entry) - {ID} - SEED - OVERRIDES:
            if key in EXPECTATIONS:
                assert EXPECTATIONS[key] in calls, (entry_id, key)
            else:
                assert key in reads, (entry_id, f"custom key {key!r} is never read")
        assert not {"targets", "interactions"} <= set(entry), entry_id


def test_expectation_shapes_and_path_placeholders() -> None:
    def check_target(item: dict[str, Any]) -> None:
        assert set(item) <= {"method", "path", "payload", "status_code", "response"}, item
        assert {"method", "path", "response"} <= set(item)
        assert item["path"].startswith("/api/") and ":tid" in item["path"]

    seen = Counter()
    for entry in _all_entries().values():
        for item in entry.get("targets", []):
            check_target(item)
            seen["targets"] += 1
        for block in entry.get("tenants", []):
            assert set(block) <= {"tenant", "settings", "policy", "targets"}
            assert re.fullmatch(r"\{tenant_id\d+\}", block["tenant"])
            for item in block.get("targets", []):
                check_target(item)
                seen["tenant targets"] += 1
        for interaction in entry.get("interactions", []):
            assert set(interaction) == {"request", "response"}
            assert set(interaction["request"]) <= {"method", "path", "body"}
            assert set(interaction["response"]) <= {"status", "body"}
            seen["interactions"] += 1
    assert seen["targets"] >= 10 and seen["tenant targets"] >= 2 and seen["interactions"] >= 1
    statuses = {t.get("status_code") for e in _all_entries().values() for t in e.get("targets", [])}
    assert 403 in statuses  # a permission test


def test_seed_holds_only_settings_policy_and_tenants() -> None:
    for entry_id, entry in _all_entries().items():
        settings = entry.get("settings", {})
        assert set(settings) <= {"capabilities", "roles", "api_tokens"}, entry_id
        assert set(entry.get("policy", {})) <= {"rules", "profiles"}, entry_id


def test_stacked_parametrize_and_priority_override(items: list[dict[str, Any]]) -> None:
    by_name = {i["name"]: i for i in items}
    # @parametrize("change", ...) above @parametrize("role", ...): role comes first.
    assert "test_policy_api_rules_update_forbidden[viewer-replace]" in by_name
    assert "test_policy_api_rules_update_forbidden[replace-viewer]" not in by_name
    assert "test_policy_api_rules_update_forbidden[viewer-replace]" in _all_entries()
    assert by_name["test_rules_add_basic[allow]"]["priority"] == "p0"  # from the decorator
    assert by_name["test_rules_add_basic[deny]"]["priority"] == "p2"  # from the JSON entry


def test_all_tests_carry_the_four_markers_with_known_values(items: list[dict[str, Any]]) -> None:
    markers = Settings().markers
    for item in items:
        m = item["markers"]
        assert set(m) == {"priority", "project", "component", "suite"}, item["nodeid"]
        assert item["priority"] in markers.priorities
        assert m["project"] == [markers.project]
        assert m["suite"][0] in markers.suites


# --- Class scaffold, page objects, assertions -------------------------------------------


def test_classes_use_the_base_class_scaffold_and_setup() -> None:
    styles = Counter()
    for _path, cls in _test_classes():
        assert [_dotted(b) for b in cls.bases] == ["BaseTest"], cls.name
        decorators = [_dotted(d) for d in cls.decorator_list]
        assert decorators[-2:] == ["pytest.mark.project", "pytest.mark.component"], cls.name
        assert "environments" in decorators, cls.name
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        if "setup" in methods:
            assert "self.base_setup" in _calls(methods["setup"]), cls.name
            styles["setup"] += 1
        if "setup_method" in methods:
            styles["setup_method"] += 1
        styles["teardown"] += "teardown" in methods
        styles["data_driven" if "data_driven" in decorators else "params argument"] += 1
    assert styles["setup"] >= 3 and styles["setup_method"] >= 1 and styles["teardown"] >= 1
    assert styles["data_driven"] >= 3 and styles["params argument"] >= 1


def test_base_setup_options_vary_by_class() -> None:
    options = set()
    for _path, cls in _test_classes():
        for node in ast.walk(cls):
            if isinstance(node, ast.Call) and _dotted(node.func) == "self.base_setup":
                options |= {k.arg for k in node.keywords}
    assert {"fresh_driver", "policy_wait"} <= options


def test_page_objects_use_properties_and_never_chain() -> None:
    setters = 0
    for path in (STANDIN / "framework" / "pages").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef):
                setters += any(_dotted(d).endswith(".setter") for d in node.decorator_list)
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
                assert node.value.id != "self", path.name  # actions return nothing
    assert setters >= 15
    for path, _cls, function in _test_functions():
        for statement in function.body:
            for node in ast.walk(statement):
                is_chained = isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call)
                assert not is_chained, (path.name, function.name)


def test_save_flows_use_the_shared_top_bar() -> None:
    flows = Counter()
    for _path, _cls, function in _test_functions():
        calls = _calls(function)
        flows["publish"] += "top_bar.publish" in calls
        flows["reset"] += "top_bar.reset" in calls
        flows["settings save"] += any(
            isinstance(n, ast.Call)
            and _dotted(n.func).endswith("top_bar.save")
            and any(k.arg == "settings" for k in n.keywords)
            for n in ast.walk(function)
        )
    assert flows["publish"] >= 8 and flows["reset"] >= 2 and flows["settings save"] >= 2


def test_checks_use_the_unittest_assertion_object() -> None:
    for path, _cls, function in _test_functions():
        assert not any(isinstance(n, ast.Assert) for n in ast.walk(function)), function.name
        calls = _calls(function)
        checks = {c for c in calls if c.startswith("self.check.assert")}
        assert checks or calls & set(EXPECTATIONS.values()), (path.name, function.name)
    tc_methods = {
        c.removeprefix("self.check.")
        for _p, _c, f in _test_functions()
        for c in _calls(f)
        if c.startswith("self.check.")
    }
    assert {"assertEqual", "assertIn", "assertNotIn", "assertFalse"} <= tc_methods


def test_test_names_summarize_area_and_never_contain_ticket_ids() -> None:
    pattern = re.compile(Settings().eval.ticket_id_pattern)
    for path, cls, function in _test_functions():
        area = path.stem.removeprefix("test_")
        assert function.name.startswith(f"test_{area}_"), function.name
        assert len(function.name.split("_")) >= 4, function.name
        assert not pattern.search(function.name) and not re.search(r"\d{3,}", function.name)
        assert not re.search(r"\d{3,}", cls.name)


# --- Placeholders and repetition ---------------------------------------------------------


def test_unique_names_use_the_test_id_placeholder() -> None:
    for entry_id, entry in _all_entries().items():
        blocks = [entry, *entry.get("tenants", [])]
        for block in blocks:
            policy = block.get("policy", {})
            for obj in policy.get("rules", []) + policy.get("profiles", []):
                assert re.search(r"\{test_id:\d+\}", obj["name"]), (entry_id, obj["name"])


def test_placeholders_resolve_like_the_code_helper(standin: dict[str, ModuleType]) -> None:
    placeholders = standin["framework.placeholders"]
    resolved = placeholders.resolve(
        {"name": "{test_id:24}", "tenant": "{tenant_id2}", "roles": {"{user_1}": "viewer"}},
        "test_rules_add_basic[allow]",
        SUFFIX,
    )
    assert resolved == {
        "name": "rules-add-basic-a-abc123",
        "tenant": "tenant-b",
        "roles": {"user1@example.com": "viewer"},
    }
    assert len(resolved["name"]) <= 24
    assert placeholders.unique_name("test_rules_add_basic[allow]", SUFFIX, 24) == resolved["name"]


def test_large_seed_blocks_repeat_across_variants() -> None:
    entries = _by_id("tests/rules/test_rules.py")
    prefixes = ("test_rules_list_search", "test_rules_list_filter", "test_rules_list_pagination")
    lists = [e["policy"] for k, e in entries.items() if k.startswith(prefixes)]
    assert len(lists) >= 6 and all(p == lists[0] for p in lists)
    assert len(json.dumps(lists[0])) > 1000
    capabilities = Counter(json.dumps(e["settings"], sort_keys=True) for e in entries.values())
    assert capabilities.most_common(1)[0][1] >= len(entries) - 2


def test_variants_differ_by_one_or_two_values() -> None:
    entries = _by_id("tests/rules/test_rules.py")
    exact, partial = (
        entries["test_rules_list_search[exact]"],
        entries["test_rules_list_search[partial]"],
    )
    differing = {k for k in exact if exact[k] != partial[k]}
    assert differing == {ID, "query", "expected_count"}


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


# --- Skips --------------------------------------------------------------------------------


def test_entry_skip_cites_a_ticket_id(items: list[dict[str, Any]]) -> None:
    pattern = re.compile(Settings().eval.ticket_id_pattern)
    skipped = [i for i in items if any(pattern.search(r) for r in i["skips"])]
    assert [i["name"] for i in skipped] == ["test_profiles_edit_reset"]
    assert skipped[0]["skips"][0].startswith("STND-105:")


def test_deployment_type_skips(
    items: list[dict[str, Any]], on_prem_items: list[dict[str, Any]]
) -> None:
    def skipped(collected: list[dict[str, Any]]) -> set[str]:
        return {i["name"] for i in collected if any("only test" in r for r in i["skips"])}

    assert skipped(items) == {"test_settings_capabilities_disable_profiles"}
    assert skipped(on_prem_items) == {
        "test_tenants_secondary_rules_add",
        "test_tenants_secondary_rules_list",
    }


def test_platform_selection_skips_browser_classes_only() -> None:
    collected = _collect("cloud", browser="safari")
    skipped = {i["file"] for i in collected if any("runs only on" in r for r in i["skips"])}
    assert "tests/api/test_policy_api.py" not in skipped  # no browser, no platform selection
    assert "tests/rules/test_rules.py" in skipped


# --- Test kinds (manifest) --------------------------------------------------------------


def test_manifest_covers_exactly_the_collected_functions(items: list[dict[str, Any]]) -> None:
    assert set(MANIFEST["tests"]) == {i["function"] for i in items}


def test_test_kind_mix() -> None:
    kinds = Counter(t["kind"] for t in MANIFEST["tests"].values())
    total = sum(kinds.values())
    assert total >= 25
    assert 0.80 <= kinds["ui"] / total <= 0.92
    assert kinds["api"] >= 1 and kinds["hybrid"] >= 1


def test_api_tests_never_touch_the_browser() -> None:
    kinds = {f.split("::")[-1]: info["kind"] for f, info in MANIFEST["tests"].items()}
    for _path, _cls, function in _test_functions():
        if kinds[function.name] != "api":
            continue
        used = {_dotted(n) for n in ast.walk(function) if isinstance(n, ast.Attribute)}
        assert not any(u.startswith(("self.nav", "self.driver")) for u in used), function.name


# --- Expectations replay against the app (in process, no server) -------------------------


@pytest.fixture
def standin() -> Iterator[dict[str, ModuleType]]:
    sys.path.insert(0, str(STANDIN))
    names = (
        "app.state",
        "app.server",
        "framework.config",
        "framework.data",
        "framework.placeholders",
        "framework.validations",
    )
    try:
        yield {name: importlib.import_module(name) for name in names}
    finally:
        sys.path.remove(str(STANDIN))


Effect = Callable[[Any, dict[str, Any], str, str], Any]


def _effects() -> dict[str, Effect]:
    """The backend effect of each UI flow: (store, entry, unique name, tenant) -> None."""

    def add_rule(action: str, **extra: Any) -> Effect:
        def run(s: Any, e: dict[str, Any], name: str, t: str) -> None:
            s.add_rule(t, {"name": name, "action": action, **extra})
            s.save(t)
            s.publish(t)

        return run

    def then_publish(change: Callable[[Any, dict[str, Any], str, str], Any]) -> Effect:
        def run(s: Any, e: dict[str, Any], name: str, t: str) -> None:
            change(s, e, name, t)
            s.save(t)
            s.publish(t)

        return run

    imported = json.loads((STANDIN / "tests/rules/files/rules_import.json").read_text("utf-8"))
    return {
        "test_rules_add_basic[allow]": add_rule("allow"),
        "test_rules_add_basic[deny]": add_rule("deny"),
        "test_rules_add_with_condition": add_rule(
            "log", conditions=[{"field": "region", "value": "north"}]
        ),
        "test_rules_edit_action": then_publish(
            lambda s, e, n, t: s.update_rule(t, n, {"action": "deny"})
        ),
        "test_rules_edit_disable": then_publish(
            lambda s, e, n, t: s.update_rule(t, n, {"enabled": False})
        ),
        "test_rules_edit_reset": lambda s, e, n, t: (
            s.update_rule(t, n, {"action": "deny"}),
            s.discard(t),
        ),
        "test_rules_delete_single": then_publish(
            lambda s, e, n, t: s.delete_rules(t, [e["delete_name"]])
        ),
        "test_rules_delete_several": then_publish(
            lambda s, e, n, t: s.delete_rules(t, e["delete_names"])
        ),
        "test_rules_import_file": then_publish(lambda s, e, n, t: s.import_rules(t, imported)),
        "test_profiles_add_basic": then_publish(
            lambda s, e, n, t: s.add_profile(t, {"name": n, "level": "medium"})
        ),
        "test_profiles_edit_level[low]": then_publish(
            lambda s, e, n, t: s.update_profile(t, n, {"level": "low"})
        ),
        "test_profiles_edit_level[high]": then_publish(
            lambda s, e, n, t: s.update_profile(t, n, {"level": "high"})
        ),
        "test_profiles_delete_created": lambda s, e, n, t: (
            then_publish(
                lambda s, e, n, t: (
                    s.add_profile(t, {"name": e["keep_name"], "level": "low"}),
                    s.add_profile(t, {"name": e["delete_name"], "level": "high"}),
                )
            )(s, e, n, t),
            then_publish(lambda s, e, n, t: s.delete_profile(t, e["delete_name"]))(s, e, n, t),
        ),
        "test_profiles_edit_reset": lambda s, e, n, t: (
            s.update_profile(t, n, {"level": "high"}),
            s.discard(t),
        ),
        "test_settings_capabilities_enable_bulk": lambda s, e, n, t: s.update_capabilities(
            t, {"bulk_delete": True}
        ),
        "test_settings_capabilities_disable_profiles": lambda s, e, n, t: s.update_capabilities(
            t, {"profiles": False}
        ),
        "test_tenants_secondary_rules_add": lambda s, e, n, t: add_rule("deny")(
            s, e, n, "tenant-b"
        ),
    }


def _replay(standin: dict[str, ModuleType], test_id: str, effect: Effect | None) -> None:
    """Seed from the entry, run the flow's backend effect, then check every expectation."""
    state, server = standin["app.state"], standin["app.server"]
    config = standin["framework.config"].CONFIG
    placeholders, validations = standin["framework.placeholders"], standin["framework.validations"]
    entry = placeholders.resolve(_all_entries()[test_id], test_id, SUFFIX)
    primary = config.tenants[0]
    store = server.STORE
    store.reset()
    service = {"roles": {config.service_user: "admin"}}
    blocks = [{"tenant": t, "settings": service} for t in config.tenants]
    store.seed(blocks + standin["framework.data"].seed_blocks(entry, primary))
    if effect is not None:
        effect(store, entry, placeholders.unique_name(test_id, SUFFIX, 24), primary)

    user = config.users[0] if test_id.startswith("test_policy_api_") else config.service_user
    checks = [(primary, t) for t in entry.get("targets", [])]
    checks += [(b["tenant"], t) for b in entry.get("tenants", []) for t in b.get("targets", [])]
    checks += [
        (
            primary,
            {
                "method": i["request"]["method"],
                "path": i["request"]["path"],
                "payload": i["request"].get("body"),
                "status_code": i["response"].get("status", 200),
                "response": i["response"].get("body"),
            },
        )
        for i in entry.get("interactions", [])
    ]
    assert checks, test_id
    for tenant, item in checks:
        path = validations.fill_path(item["path"], tenant, store.tenant(tenant).rev_id)
        parts = [p for p in path.removeprefix("/api/").split("/") if p]
        try:
            status = 200
            body = server.route_api(item["method"], parts, item.get("payload"), user)
        except state.PermissionDenied as error:
            status, body = 403, {"error": str(error)}
        except state.ValidationError as error:
            status, body = 422, {"error": str(error)}
        assert status == item.get("status_code", 200), (test_id, path, body)
        if item.get("response") is not None:
            validations.matches_subset(body, item["response"])


def _with_expectations() -> list[str]:
    return [
        test_id
        for test_id, entry in _all_entries().items()
        if entry.get("targets")
        or entry.get("interactions")
        or any(b.get("targets") for b in entry.get("tenants", []))
    ]


def test_every_expectation_is_covered_by_a_replay() -> None:
    api_only = {i for i in _with_expectations() if i.startswith("test_policy_api_")}
    assert set(_with_expectations()) - api_only <= set(_effects())


@pytest.mark.parametrize("test_id", _with_expectations())
def test_expectations_replay_against_the_app(standin: dict[str, ModuleType], test_id: str) -> None:
    _replay(standin, test_id, _effects().get(test_id))


def test_open_bug_shows_in_the_ui_view(standin: dict[str, ModuleType]) -> None:
    """STND-105 (open): after a reset, the UI still shows the profile edit."""
    test_id = "test_profiles_edit_reset"
    _replay(standin, test_id, _effects()[test_id])
    name = standin["framework.placeholders"].unique_name(test_id, SUFFIX, 24)
    tenant = standin["framework.config"].CONFIG.tenants[0]
    shown = standin["app.server"].STORE.search_profiles(tenant, name)
    assert [p["level"] for p in shown] == ["high"]  # the test expects "low", so it is skipped


def test_ui_only_expectations_match_the_app(standin: dict[str, ModuleType]) -> None:
    placeholders, server = standin["framework.placeholders"], standin["app.server"]
    config = standin["framework.config"].CONFIG
    store = server.STORE

    def seeded(test_id: str) -> dict[str, Any]:
        entry = placeholders.resolve(_all_entries()[test_id], test_id, SUFFIX)
        store.reset()
        store.seed(standin["framework.data"].seed_blocks(entry, config.tenants[0]))
        return entry

    tenant = config.tenants[0]
    for match in ("exact", "partial", "mixed_case"):
        entry = seeded(f"test_rules_list_search[{match}]")
        assert store.list_rules(tenant, entry["query"])[1] == entry["expected_count"], match
    for action in ("allow", "deny"):
        entry = seeded(f"test_rules_list_filter_action[{action}]")
        assert store.list_rules(tenant, "", action)[1] == entry["expected_count"], action
    entry = seeded("test_rules_list_pagination")
    assert len(store.list_rules(tenant, "", "allow", 2)[0]) == entry["last_page_count"]
    entry = seeded("test_profiles_list_search")
    assert [p["name"] for p in store.search_profiles(tenant, "team")] == entry["expected_names"]
    entry = seeded("test_rules_add_duplicate_name")
    name = placeholders.unique_name("test_rules_add_duplicate_name", SUFFIX, 24)
    with pytest.raises(standin["app.state"].ValidationError, match="already exists"):
        store.add_rule(tenant, {"name": name})


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
        "Fix STND-103: reject duplicate rule names",
        "Fix STND-104: deleted rules stay deleted after publishing",
    ]
    pattern = re.compile(Settings().eval.ticket_id_pattern)
    for rev, ticket in (("HEAD~1", "STND-103"), ("HEAD", "STND-104")):
        removed = [
            line
            for line in git("show", "--format=", rev, "--", "tests").splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
        assert any(ticket in pattern.findall(line) for line in removed), rev
    assert "skip" not in _by_id("tests/rules/test_rules.py")["test_rules_delete_single"]


# --- App state (no server needed) -------------------------------------------------------


def test_app_state_layers_and_revisions(standin: dict[str, ModuleType]) -> None:
    state = standin["app.state"]
    store = state.Store()
    store.seed([{"tenant": "t1", "policy": {"rules": [{"name": "a"}]}}])
    tenant = store.tenant("t1")
    assert tenant.rev_id == 1 and not tenant.has_unsaved_changes
    store.add_rule("t1", {"name": "b", "action": "deny"})
    assert tenant.has_unsaved_changes and store.published("t1", 1)["rules"] == [
        state._rule({"name": "a"})
    ]
    with pytest.raises(state.ValidationError, match="Save your changes"):
        store.publish("t1")
    store.save("t1")
    assert store.publish("t1") == 2
    assert [r["name"] for r in store.published("t1", 2)["rules"]] == ["a", "b"]
    with pytest.raises(state.ValidationError, match="already exists"):
        store.add_rule("t1", {"name": "a"})
    with pytest.raises(state.ValidationError, match="several rules"):
        store.delete_rules("t1", ["a", "b"])
    with pytest.raises(state.PermissionDenied):
        store.api_replace_rules("t1", "nobody@example.com", [])
    assert store.list_rules("t1", "A")[1] == 1  # case-insensitive search


# --- Generic names only -----------------------------------------------------------------


def test_only_generic_hosts_in_the_standin() -> None:
    allowed = {"localhost", "127.0.0.1", "example.com", "jira.example.com"}
    host = re.compile(r"https?://([A-Za-z0-9.-]+)")
    email_domain = re.compile(r"(?<=[\w}])@([A-Za-z0-9-]+\.[A-Za-z0-9.-]+)")
    for path in STANDIN.rglob("*"):
        if path.suffix not in {".py", ".json", ".md", ".ini", ".toml"}:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text("utf-8")
        for found in host.findall(text) + email_domain.findall(text):
            assert found in allowed, f"{path.relative_to(STANDIN)}: {found}"
