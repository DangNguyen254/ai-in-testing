"""Indexer: extraction, chunks, symbol catalog, caching, incremental rebuilds, and search."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path, PurePosixPath

import pytest
from typer.testing import CliRunner

from tests.conftest import REPO_ROOT
from tests.test_standin import _collect
from ticket2test.adapters.repo.local_path import LocalPathRepoSource, RepoReadError
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.index.extract import ParseError, extract_file
from ticket2test.index.indexer import IndexData, build_index, index_dir, load_index, update_index

STANDIN = REPO_ROOT / "standin"
HTTPX = REPO_ROOT / ".scratch" / "repos" / "httpx"
needs_httpx = pytest.mark.skipif(
    not (HTTPX / "httpx").is_dir(),
    reason="httpx not cloned: git clone --depth 1 --branch 0.28.1 "
    "https://github.com/encode/httpx .scratch/repos/httpx",
)


def _settings(tmp_path: Path) -> Settings:
    return Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}})


@pytest.fixture(scope="module")
def standin_index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    settings = _settings(tmp_path_factory.mktemp("standin"))
    data, stats, _ = update_index(STANDIN, settings)
    assert stats.skipped == []
    return data


@pytest.fixture(scope="module")
def httpx_index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    if not (HTTPX / "httpx").is_dir():
        pytest.skip("httpx not cloned")
    data, _, _ = update_index(HTTPX, _settings(tmp_path_factory.mktemp("httpx")))
    return data


def _chunk(data: IndexData, qualname: str) -> object:
    return next(c for c in data.chunks if c.qualname == qualname)


# --- RepoSource ------------------------------------------------------------------------------


def test_local_repo_source_is_read_only_and_skips(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "gen_pb2.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "b.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "bin.py").write_bytes(b"\x00\x01binary")
    (tmp_path / "big.py").write_text("#" * 200, encoding="utf-8")
    repo = LocalPathRepoSource(tmp_path, ignore=["build", "*_pb2.py"], max_file_bytes=100)

    assert sorted(map(str, repo.list_files())) == ["big.py", "bin.py", "pkg/a.py"]
    with pytest.raises(RepoReadError, match="binary"):
        repo.read_text(PurePosixPath("bin.py"))
    with pytest.raises(RepoReadError, match="limit"):
        repo.read_text(PurePosixPath("big.py"))
    with pytest.raises(RepoReadError, match="outside"):
        repo.read_text(PurePosixPath("../escape.py"))
    assert not [name for name in dir(repo) if name.startswith(("write", "delete", "remove"))]


# --- extraction ------------------------------------------------------------------------------


def test_extract_whole_definitions_with_decorators() -> None:
    source = (STANDIN / "tests" / "rules" / "test_rules.py").read_bytes()
    info = extract_file("tests/rules/test_rules.py", source)
    test_class = info.classes[0]
    method = next(m for m in test_class.methods if m.name == "test_rules_add_basic")
    assert method.code.startswith('@pytest.mark.priority("p0")')
    assert method.code.rstrip().endswith("self.verify_targets()")
    assert method.decorators[-1] == 'pytest.mark.parametrize("action", ["allow", "deny"])'
    assert test_class.decorators == [
        'browsers("chrome", "firefox")',
        'environments("cloud", "on_prem")',
        "data_driven",
        'pytest.mark.project("example-project")',
        'pytest.mark.component("rules")',
    ]
    assert info.imports[0] == "from pathlib import Path"
    # Unannotated code: types come from what a function returns.
    nav_info = extract_file(
        "framework/pages/nav.py", (STANDIN / "framework" / "pages" / "nav.py").read_bytes()
    )
    rules = next(m for m in nav_info.classes[0].methods if m.name == "rules")
    assert rules.returns is None and rules.returned_calls == ["RulesArea"]
    assert "def " not in test_class.header_code  # class chunk header has no methods


def test_extract_rejects_syntax_errors() -> None:
    with pytest.raises(ParseError, match="syntax error near line"):
        extract_file("bad.py", b"def ok():\n    return (\n")


# --- chunks ----------------------------------------------------------------------------------


def test_test_chunks_carry_decorators_markers_ids_and_entries(standin_index: IndexData) -> None:
    chunk = _chunk(standin_index, "TestRules.test_rules_list_search")
    assert chunk.kind == "test"  # type: ignore[attr-defined]
    assert chunk.class_name == "TestRules"  # type: ignore[attr-defined]
    assert {m.name: m.args for m in chunk.markers} == {  # type: ignore[attr-defined]
        "priority": ["p2"],
        "suite": ["regression"],
        "project": ["example-project"],
        "component": ["rules"],
    }
    assert [p.argnames for p in chunk.parametrize] == [["match"]]  # type: ignore[attr-defined]
    assert chunk.test_ids == [  # type: ignore[attr-defined]
        "test_rules_list_search[exact]",
        "test_rules_list_search[partial]",
        "test_rules_list_search[mixed_case]",
    ]
    assert chunk.data_file == "tests/rules/test_rules.json"  # type: ignore[attr-defined]
    assert chunk.data_format == "array"  # type: ignore[attr-defined]
    assert set(chunk.data_entries) == set(chunk.test_ids)  # type: ignore[attr-defined]
    entry = chunk.data_entries["test_rules_list_search[partial]"]  # type: ignore[attr-defined]
    assert entry["test_id"] == "test_rules_list_search[partial]"
    assert (entry["query"], entry["total_count"]) == ("alpha", 3)


def test_stacked_parametrize_ids_put_the_bottom_decorator_first(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text(
        "import pytest\n\n\n"
        '@pytest.mark.parametrize("mode", ["typed", "pasted"])\n'
        '@pytest.mark.parametrize("quantity", ["0", "-1"])\n'
        "def test_x(quantity, mode):\n    pass\n",
        encoding="utf-8",
    )
    data, _ = build_index(LocalPathRepoSource(tmp_path), _settings(tmp_path))
    chunk = next(c for c in data.chunks if c.kind == "test")
    assert chunk.test_ids == [
        "test_x[0-typed]",
        "test_x[0-pasted]",
        "test_x[-1-typed]",
        "test_x[-1-pasted]",
    ]


def test_static_ids_match_pytest_collect_only(standin_index: IndexData) -> None:
    collected = {(i["file"], i["name"]) for i in _collect("cloud")}
    tests = [c for c in standin_index.chunks if c.kind == "test"]
    assert all(c.test_ids_computed for c in tests)
    static = {(c.file_path, name) for c in tests for name in c.test_ids}
    assert static == collected


def test_page_objects_are_chunked_whole(standin_index: IndexData) -> None:
    page = _chunk(standin_index, "RuleListPage")
    assert page.kind == "page_object"  # type: ignore[attr-defined]
    assert "def search(" in page.code and "def rule_names(" in page.code  # type: ignore[attr-defined]
    assert "@search_text.setter" in page.code  # type: ignore[attr-defined]
    plain = _chunk(standin_index, "ApiClient")
    assert plain.kind == "class"  # type: ignore[attr-defined]
    assert "def request(" not in plain.code  # type: ignore[attr-defined]


# --- symbol catalog --------------------------------------------------------------------------


def test_catalog_confirms_existence_and_non_existence(standin_index: IndexData) -> None:
    catalog = standin_index.catalog
    for name in ("BaseTest", "RuleWizardPage", "unique_name", "verify_targets", "base_setup"):
        assert catalog.has(name), name
    for name in (
        "RuleWizzardPage",
        "validate_backend",
        "make_unique_name",
        "nav.rules.basket",
    ):
        assert not catalog.has(name), name
    assert catalog.fixtures["params"] is False and catalog.fixtures["_framework"] is False
    assert catalog.markers["priority"] == ["p0", "p1", "p2", "p3"]
    assert catalog.markers["suite"] == ["regression", "smoke"]


@pytest.mark.parametrize(
    ("chain", "status"),
    [
        ("nav.rules.list.search", "ok"),
        ("nav.rules.wizard.next", "ok"),
        ("nav.top_bar.publish", "ok"),
        ("nav.settings.capabilities.bulk_delete_enabled", "ok"),  # a property with a setter
        ("nav.rules.list.toast", "ok"),  # inherited from BasePage
        ("nav.rules.basket", "missing"),
        ("nav.rules.wizard.submit", "missing"),
        ("nav.rules.list.driver.get", "unknown_type"),  # selenium type, can't check
        ("api.items", "no_root"),  # not a configured chain root
    ],
)
def test_property_chains(standin_index: IndexData, chain: str, status: str) -> None:
    assert standin_index.catalog.resolve_chain_from_roots(chain).status == status


def test_chains_from_a_test_class_including_calls(standin_index: IndexData) -> None:
    catalog = standin_index.catalog
    ok = catalog.resolve_chain("TestRules", ["nav", "rules", "wizard", "save"])
    assert ok.ok
    # Actions return nothing, so chaining after one can't resolve.
    chained = catalog.resolve_chain("TestRules", ["nav", "rules", "wizard", "next()", "save"])
    assert chained.status == "unknown_type"
    missing = catalog.resolve_chain("TestProfiles", ["policy", "add_rules"])
    assert missing.status == "missing" and missing.failed_step == 1
    assert catalog.resolve_chain("TestProfiles", ["policy", "add_rule"]).ok
    # The assertion object is a unittest.TestCase (outside the repo): not checkable further.
    assert catalog.resolve_chain("TestRules", ["check", "assertEqual"]).status == "unknown_type"
    assert "nav.rules.wizard.condition_value" in {c.chain for c in catalog.chains}


# --- indexer: cache, incremental, errors -----------------------------------------------------


def _copy_standin(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(STANDIN, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


def test_cache_reloads_without_reparsing(tmp_path: Path) -> None:
    repo, settings = _copy_standin(tmp_path), _settings(tmp_path)
    first, stats, path = update_index(repo, settings)
    assert stats.parsed == stats.files > 0
    assert path.parent == index_dir(repo, settings)

    loaded = load_index(index_dir(repo, settings), settings)
    assert loaded is not None
    assert loaded.chunks == first.chunks and loaded.tokens == first.tokens

    _, again, _ = update_index(repo, settings)
    assert again.parsed == 0 and again.reused == stats.files


def test_incremental_rebuild_parses_only_changed_files(tmp_path: Path) -> None:
    repo, settings = _copy_standin(tmp_path), _settings(tmp_path)
    update_index(repo, settings)
    target = repo / "framework" / "placeholders.py"
    target.write_text(
        target.read_text("utf-8") + "\n\ndef brand_new_helper() -> None:\n    pass\n", "utf-8"
    )

    data, stats, _ = update_index(repo, settings)
    assert stats.parsed == 1
    assert data.catalog.has("brand_new_helper")

    _, forced, _ = update_index(repo, settings, force=True)
    assert forced.parsed == forced.files


def test_settings_change_invalidates_the_cache(tmp_path: Path) -> None:
    repo, settings = _copy_standin(tmp_path), _settings(tmp_path)
    update_index(repo, settings)
    changed = settings.model_copy(
        update={"index": settings.index.model_copy(update={"name_boost": 5})}
    )
    assert load_index(index_dir(repo, changed), changed) is None


def test_parse_errors_are_logged_and_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repo, settings = _copy_standin(tmp_path), _settings(tmp_path)
    (repo / "framework" / "broken.py").write_text("def nope(:\n", encoding="utf-8")
    (repo / "framework" / "latin1.py").write_bytes(b"# caf\xe9\n")
    with caplog.at_level(logging.WARNING):
        data, stats, _ = update_index(repo, settings)
    reasons = {s.path: s.reason for s in stats.skipped}
    assert set(reasons) == {"framework/broken.py", "framework/latin1.py"}
    assert "syntax error" in reasons["framework/broken.py"]
    assert "UTF-8" in reasons["framework/latin1.py"]
    assert "broken.py" in caplog.text
    assert any(c.kind == "test" for c in data.chunks)  # everything else still indexed


def test_missing_data_file_is_not_fatal(tmp_path: Path) -> None:
    repo, settings = _copy_standin(tmp_path), _settings(tmp_path)
    (repo / "tests" / "profiles" / "test_profiles.json").unlink()
    data, _ = build_index(LocalPathRepoSource(repo), settings)
    chunk = next(c for c in data.chunks if c.qualname == "TestProfiles.test_profiles_add_basic")
    assert chunk.data_file is None and chunk.data_entries == {}


@needs_httpx
def test_index_httpx(httpx_index: IndexData) -> None:
    kinds = {c.kind for c in httpx_index.chunks}
    assert {"test", "function", "class"} <= kinds
    assert sum(c.kind == "test" for c in httpx_index.chunks) > 400
    assert httpx_index.catalog.has("Client") and httpx_index.catalog.has("DigestAuth")
    assert not httpx_index.catalog.has("DigestAuthenticator")


# --- search: known functions/pages return their tests in the top 5 --------------------------


@needs_httpx
@pytest.mark.parametrize(
    "symbol", ["get_environment_proxies", "URLPattern", "DigestAuth", "Cookies", "BasicAuth"]
)
def test_search_known_httpx_functions(httpx_index: IndexData, symbol: str) -> None:
    """Searching a function/class name returns tests that use it, within the top 5."""
    assert httpx_index.catalog.has(symbol)
    uses = re.compile(rf"\b{re.escape(symbol)}\b")
    its_tests = {c.id for c in httpx_index.chunks if c.kind == "test" and uses.search(c.code)}
    assert its_tests, f"no test references {symbol}"
    hits = httpx_index.search_index().search(symbol, top_k=5, kinds={"test"})
    assert {h.chunk.id for h in hits} & its_tests, [h.chunk.id for h in hits]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("wizard", "tests/rules/test_rules.py::TestRules.test_rules_add_basic"),
        (
            "capabilities",
            "tests/settings/test_settings.py::TestSettingsCapabilities"
            ".test_settings_capabilities_enable_bulk",
        ),
    ],
)
def test_search_known_standin_pages(standin_index: IndexData, query: str, expected: str) -> None:
    hits = standin_index.search_index().search(query, top_k=5, kinds={"test"})
    assert expected in {h.chunk.id for h in hits}, [h.chunk.id for h in hits]


def test_search_edge_cases(standin_index: IndexData) -> None:
    index = standin_index.search_index()
    assert index.search("") == []
    assert index.search("zzzzqqq") == []
    pages = index.search("search rules", top_k=3, kinds={"page_object"})
    assert pages and all(h.chunk.kind == "page_object" for h in pages)


# --- CLI -------------------------------------------------------------------------------------


def test_cli_index_and_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T2T_PATHS__CACHE_DIR", str(tmp_path / "cache"))
    runner = CliRunner()
    result = runner.invoke(app, ["index", str(STANDIN)])
    assert result.exit_code == 0, result.output
    assert "42 files" in result.output and "page-object chains: 505" in result.output

    result = runner.invoke(
        app, ["search", "delete rule", "--repo", str(STANDIN), "--kind", "test", "--top-k", "3"]
    )
    assert result.exit_code == 0, result.output
    assert "TestRules.test_rules_delete_single" in result.output
    assert len(result.output.strip().splitlines()) == 3


def test_cli_search_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T2T_PATHS__CACHE_DIR", str(tmp_path / "cache"))
    runner = CliRunner()
    missing = runner.invoke(app, ["search", "x", "--repo", str(tmp_path)])
    assert missing.exit_code == 1 and "Run `ticket2test index" in missing.output
    bad_kind = runner.invoke(app, ["search", "x", "--repo", str(tmp_path), "--kind", "widget"])
    assert bad_kind.exit_code == 2
    not_dir = runner.invoke(app, ["index", str(tmp_path / "nope")])
    assert not_dir.exit_code == 2


# --- syntax-tree references ------------------------------------------------------------------

_REFS_SOURCE = b'''class T(Base):
    """Class doc mentions helper()."""
    LOC = (By.ID, "x")

    @retry(times=2)
    def f(self, a, b=DEFAULT, *, c: Kind = 2) -> Result:
        """doc mentions build_request()"""
        # comment build_request()
        x = g(base_url=a, key=f"{h(y)} text 'not_a_ref()'")
        self.nav.users.invite.open().invite(e, r)
        self.api.items()
        self.client: Client = make_client(self.config)
        return [z for z in other.values()]
'''


def test_refs_come_from_the_syntax_tree() -> None:
    info = extract_file("t.py", _REFS_SOURCE)
    refs = info.classes[0].methods[0].refs
    assert refs.calls == ["retry", "g", "h", "invite", "open", "items", "make_client", "values"]
    # Docstring, comment, and string-literal mentions are not references.
    assert "build_request" not in refs.names and "not_a_ref" not in refs.names
    # f-string code is; keyword names, parameter declarations, and the def's name are not.
    assert refs.names["h"] == 1 and refs.names["y"] == 1
    for not_a_ref in ("base_url", "key", "b", "c", "f", "self"):
        assert not_a_ref not in refs.names
    # Defaults, annotations, and decorators are references.
    for name in ("DEFAULT", "Kind", "Result", "retry"):
        assert name in refs.names
    assert refs.self_chains == [["nav", "users", "invite", "open()", "invite"], ["api", "items"]]


def test_self_assignments_from_the_syntax_tree() -> None:
    fn = extract_file("t.py", _REFS_SOURCE).classes[0].methods[0]
    assert [(a.name, a.annotation, a.call) for a in fn.self_assignments] == [
        ("client", "Client", "make_client")
    ]


def test_class_header_refs_exclude_methods() -> None:
    cls = extract_file("t.py", _REFS_SOURCE).classes[0]
    assert set(cls.header_refs.names) == {"Base", "LOC", "By", "ID"}
    assert "make_client" in cls.refs.names  # whole-class refs include the methods


def test_chunks_carry_refs(standin_index: IndexData) -> None:
    test = _chunk(standin_index, "TestRules.test_rules_add_basic")
    assert ["nav", "rules", "wizard"] in test.refs.self_chains  # type: ignore[attr-defined]
    assert {"next", "publish", "verify_targets", "assertEqual"} <= set(test.refs.calls)  # type: ignore[attr-defined]


# --- reuse: inherited tests and class variants -------------------------------------------------


def test_test_classes_collect_the_tests_they_inherit(standin_index: IndexData) -> None:
    chunks = {c.id: c for c in standin_index.chunks}
    defined = "tests/files/checks.py::DownloadChecks.test_files_download_verdict"
    assert chunks[defined].kind == "function"  # the shared base itself is not collected
    for test_file, cls in (
        ("test_files_downloads", "TestFilesDownloads"),
        ("test_files_scanning", "TestFilesScanning"),
        ("test_files_archives", "TestFilesArchives"),
    ):
        chunk = chunks[f"tests/files/{test_file}.py::{cls}.test_files_download_verdict"]
        assert chunk.kind == "test" and chunk.inherited_from == defined
        assert chunk.test_ids == ["test_files_download_verdict"]
        # Its data entry comes from the subclass's own data file; markers from the base method.
        assert chunk.data_entries["test_files_download_verdict"]["file"]
        assert {m.name for m in chunk.markers} >= {"priority", "suite", "component"}


def test_class_variants_are_collected_under_the_generated_classes(standin_index: IndexData) -> None:
    viewer = [
        c for c in standin_index.chunks if c.class_name == "TestFilesViewer" and c.kind == "test"
    ]
    assert {c.symbol_name for c in viewer} == {
        "test_files_viewer_strips_active_content",
        "test_files_download_verdict",  # inherited, and collected under each variant
    }
    for chunk in viewer:
        assert chunk.collected_classes == ["TestFilesViewerConverted", "TestFilesViewerOriginal"]


def test_variant_rule_names_the_generated_classes() -> None:
    from ticket2test.config import ClassVariantRule
    from ticket2test.index.inheritance import variant_classes

    rules = {"variants": ClassVariantRule(values_from=1)}
    decorators = ['browsers("chrome")', 'variants("delivery", "converted", "dry_run")']
    assert variant_classes("TestX", decorators, rules) == ["TestXConverted", "TestXDryRun"]
    custom = {"per_mode": ClassVariantRule(values_from=0, name="{cls}_{value}")}
    assert variant_classes("TestX", ['framework.per_mode("a", "b")'], custom) == [
        "TestX_a",
        "TestX_b",
    ]
    assert variant_classes("TestX", ["data_driven"], rules) is None
