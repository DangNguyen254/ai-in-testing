"""Missing pieces: candidates from generated code and hints, checked against the index."""

from __future__ import annotations

import pytest

from tests.conftest import REPO_ROOT
from tests.test_patch import _generated
from ticket2test.config import Settings
from ticket2test.gaps import check_pieces, from_generated, from_hints
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.gaps import MissingPiece
from ticket2test.models.retrieval import MissingHint

STANDIN = REPO_ROOT / "standin"


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    folder = tmp_path_factory.mktemp("idx")
    settings = Settings.model_validate({"paths": {"cache_dir": str(folder / "cache")}})
    index, _, _ = update_index(STANDIN, settings)
    return settings, index


def _piece(kind: str, owner: str, name: str) -> MissingPiece:
    return MissingPiece(
        kind=kind,  # type: ignore[arg-type]
        owner=owner,
        name=name,
        needed_for="t",
        source="investigator",
    )


@pytest.mark.parametrize(
    ("kind", "owner", "name", "status", "found", "close"),
    [
        # A real gap in the stand-in: nothing like it exists.
        ("page_object_member", "nav.files.policy", "add_blocklist_hash", "missing", None, []),
        # Haiku's false claim: it exists (used in many places; the owner was left out).
        ("helper", "", "verify_targets", "exists", "ValidationMixin.verify_targets", []),
        ("helper", "BaseTest", "verify_targets", "exists", "ValidationMixin.verify_targets", []),
        ("page_object_member", "nav.rules.list", "search_text", "exists",
         "RuleListPage.search_text", []),
        # Existing members under another name are shown, nearest first.
        ("page_object_member", "nav.rules.list", "rule_count_total", "close_match", None,
         ["RuleListPage.total_count"]),
        ("helper", "", "make_unique_name", "close_match", None, ["BaseTest.unique_name"]),
        # The same name on another test-side class; product code is never suggested.
        ("helper", "", "publish", "close_match", None, ["TopBar.publish (on another class)"]),
        # Product code and unknown owners are out.
        ("helper", "Store", "update_capabilities", "not_test_side", None, []),
        ("page_object_member", "nav.nowhere", "x", "owner_unknown", None, []),
        ("fixture", "", "params", "exists", "fixture params", []),
    ],
)  # fmt: skip
def test_verdicts(
    setup: tuple[Settings, IndexData],
    kind: str,
    owner: str,
    name: str,
    status: str,
    found: str | None,
    close: list[str],
) -> None:
    settings, index = setup
    (verdict,) = check_pieces([_piece(kind, owner, name)], index, settings)
    assert (verdict.status, verdict.found, verdict.close) == (status, found, close)


GAP_CODE = """import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("files")
class TestFilesBlocklist(BaseTest):
   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_files_blocklist_hash_added(self):
      policy = self.nav.files.policy
      policy.open()
      policy.add_blocklist_hash(self.params["hash"])
      self.nav.top_bar.publish()
      build_blocked_file(self.params["hash"])
      self.verify_targets()
"""
ENTRIES = [{"test_id": "test_files_blocklist_hash_added"}]


def test_candidates_from_generated_code(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    pieces = from_generated(_generated(GAP_CODE, ENTRIES), index, settings)
    by_name = {p.name: p for p in pieces}
    assert set(by_name) == {"add_blocklist_hash", "build_blocked_file"}  # open, publish exist
    member = by_name["add_blocklist_hash"]
    assert member.kind == "page_object_member" and member.source == "generated"
    assert member.owner.endswith("DownloadPolicyPage")
    assert "policy.add_blocklist_hash" in member.needed_for
    function = by_name["build_blocked_file"]
    assert (function.kind, function.owner) == ("helper", "")
    verdicts = {v.piece.name: v.status for v in check_pieces(pieces, index, settings)}
    assert verdicts == {"add_blocklist_hash": "missing", "build_blocked_file": "missing"}


def test_clean_code_has_no_candidates(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    lines = [
        line
        for line in GAP_CODE.splitlines(keepends=True)
        if "add_blocklist_hash" not in line and "build_blocked_file" not in line
    ]
    assert from_generated(_generated("".join(lines), ENTRIES), index, settings) == []


def test_hints_become_candidates() -> None:
    hint = MissingHint(kind="helper", owner="", name="seed_rule", needed_for="step 1")
    (piece,) = from_hints([hint])
    assert (piece.kind, piece.name, piece.source) == ("helper", "seed_rule", "investigator")


def test_generation_records_checked_gaps(
    setup: tuple[Settings, IndexData], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_patch import _ticketed
    from tests.test_reuse import SCENARIOS
    from ticket2test.generate import pipeline
    from ticket2test.generate.reuse import ReuseDecision
    from ticket2test.llm import FakeLLMClient

    settings, index = setup
    draft = SCENARIOS["method"][0]
    retrieval = _ticketed(settings, index, draft)
    decision = ReuseDecision("module", "files", False, None, None)

    def fake(*args: object, **kwargs: object) -> pipeline.ReuseOutcome:
        generated = _generated(GAP_CODE, ENTRIES)
        return pipeline.ReuseOutcome(kind="module", decision=decision, generated=generated)

    monkeypatch.setattr(pipeline, "_generate_reusing", fake)  # the generation itself is stubbed
    outcome = pipeline.generate_reusing(
        draft, retrieval, index, settings, FakeLLMClient([]), "f", "m", STANDIN
    )
    assert sorted((v.piece.name, v.status) for v in outcome.missing) == [
        ("add_blocklist_hash", "missing"),
        ("build_blocked_file", "missing"),
    ]
    assert outcome.generated is not None
    notes = [n for n in outcome.generated.review_checklist if "doesn't fully test" in n]
    assert len(notes) == 2
    assert any(
        n.startswith("The ticket needs DownloadPolicyPage.add_blocklist_hash") for n in notes
    )


def test_a_page_returned_by_a_helper_is_checked(setup: tuple[Settings, IndexData]) -> None:
    """Dev-set finding: ``editor = self.open_exception(name)`` left ``editor`` untyped, so an
    invented ``editor.clear_expiry()`` was never checked and the gap went unseen. The helper's
    ``return self.nav.exceptions.editor`` now gives the type."""
    settings, index = setup
    catalog = index.catalog
    owner = catalog.classes["tests.exceptions.exceptions_common.ExceptionsCommon"]
    defined_in, member = catalog.members_of(owner.qualname)["open_exception"]
    page = catalog._member_type(defined_in, member, owner)
    assert page is not None and page.name == "ExceptionEditorPage"
    source = (STANDIN / "tests/exceptions/test_exceptions.py").read_text(encoding="utf-8")
    code = source.replace("      editor.enabled = False\n", "      editor.clear_expiry()\n", 1)
    assert code != source
    (verdict,) = check_pieces(
        from_generated(_generated(code, []), index, settings), index, settings
    )
    assert verdict.piece.name == "clear_expiry" and verdict.owner_class == page.qualname
    assert verdict.status in ("missing", "close_match")


def test_a_page_opened_by_a_dotted_path_is_checked(setup: tuple[Settings, IndexData]) -> None:
    """Dev-set finding (STND-145): ``exceptions = self.go_to("exceptions.list")`` left the
    variable untyped, so an invented property on it was never checked. The path string now gives
    the page's type."""
    settings, index = setup
    source = (STANDIN / "tests/exceptions/test_exceptions_widgets.py").read_text(encoding="utf-8")
    code = source.replace("exceptions.help_text", "exceptions.browser_tab_title", 1)
    assert code != source
    (verdict,) = check_pieces(
        from_generated(_generated(code, []), index, settings), index, settings
    )
    assert verdict.piece.name == "browser_tab_title"
    assert verdict.owner_class == "framework.pages.exceptions.ExceptionListPage"
    assert from_generated(_generated(source, []), index, settings) == []  # the real one is fine
