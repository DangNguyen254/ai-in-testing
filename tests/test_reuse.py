"""Reuse-first: the ticket's domain (a folder), then covered, variant, method or module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.config import Settings
from ticket2test.generate.domain import Domain, DomainChoice, choose_domain, domains, full_match
from ticket2test.generate.reuse import _named_case, decide
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.models.ticket import SourceInfo, Ticket
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve

STANDIN = REPO_ROOT / "standin"


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("cache"))}}
    )
    index, _, _ = update_index(STANDIN, settings)
    return settings, index


def _draft(key: str, intent: str, steps: list[str], expected: str, **extra: Any) -> TestCaseDraft:
    return TestCaseDraft.model_validate(
        {
            "id": f"{key}/d1",
            "ticket_id": key,
            "kind": "primary",
            "intent": intent,
            "markers": {"priority": "p1", "component": "files", "suite": "regression"},
            "test_kind": "ui",
            "deployment_type": "both",
            "preconditions": [],
            "steps": steps,
            "expected_outcome": expected,
            "prompt_version": "x",
            "variants": [],
            **extra,
        }
    )


def _empty_retrieval() -> RetrievalResult:
    return RetrievalResult(ticket_id="X", repo_root=".", query_text="", hits=[])


# --- domains ------------------------------------------------------------------------------------


def test_globs_match_one_folder_level_per_star() -> None:
    assert full_match("tests/files", "tests/*")
    assert not full_match("tests/files/sub", "tests/*")
    assert full_match("suite/area/files", "suite/*/files")
    assert not full_match("tests", "tests/*")


def test_domains_are_the_matching_folders(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    names = {d.name: d.folders for d in domains(index, settings)}
    assert {"files", "agent", "rules"} <= set(names)
    assert names["files"] == ("tests/files",)
    explicit = settings.model_copy(deep=True)
    explicit.generate.domains = {"browsing": ["tests/agent", "tests/files"]}
    (only,) = domains(index, explicit)
    assert only == Domain("browsing", ("tests/agent", "tests/files"))
    assert only.contains("tests/files/test_files_downloads.py")
    assert not only.contains("tests/filesystem/x.py")


def test_component_names_the_domain_when_retrieval_says_nothing(
    setup: tuple[Settings, IndexData],
) -> None:
    settings, index = setup
    ticket = Ticket(
        id="X", title="t", components=["Agent"], source=SourceInfo(system="jira", ref="X")
    )
    choice = choose_domain(_empty_retrieval(), index, settings, ticket)
    assert choice.domain is not None and choice.domain.name == "agent"
    assert not choice.uncertain
    labelled = ticket.model_copy(update={"components": [], "labels": ["agent"]})
    choice = choose_domain(_empty_retrieval(), index, settings, labelled)
    assert choice.domain is not None and choice.domain.name == "agent"
    assert choice.uncertain  # a label alone (0.1) is below the margin
    nothing = choose_domain(_empty_retrieval(), index, settings)
    assert nothing.domain is None and nothing.uncertain


def test_standin_tickets_land_in_their_tests_domain_or_are_flagged(
    setup: tuple[Settings, IndexData],
) -> None:
    settings, index = setup
    manifest = json.loads((STANDIN / "manifest.json").read_text(encoding="utf-8"))
    source = JiraExportSource(STANDIN / "tickets" / "export.json")
    right = 0
    for key, info in manifest["tickets"].items():
        if not info["tests"]:
            continue
        ticket = normalize(source.fetch(key))
        choice = choose_domain(retrieve(ticket, index, settings), index, settings, ticket)
        wanted = {str(Path(t.split("::")[0]).parent.as_posix()) for t in info["tests"]}
        got = choice.domain.folders[0] if choice.domain else None
        right += got in wanted
        assert got in wanted or choice.uncertain, f"{key}: {choice.reason}"
    assert right == sum(1 for i in manifest["tickets"].values() if i["tests"])  # all routed


# --- reuse decisions ----------------------------------------------------------------------------

SCENARIOS = {
    "covered": (  # a near-duplicate of an existing test (strict: words alone must match)
        _draft(
            "X-1",
            "Downloading an exe file gives the verdict its file type's action decides",
            ["Download the exe file"],
            "The verdict is the decision of the exe file type's action.",
        ),
        "test_files_download_type_action",
    ),
    "variant": (
        _draft(
            "X-2",
            "A DLP rule for customer ids blocks the download",
            [
                "Add a DLP rule with a pattern for customer ids and action block",
                "Download a text file that contains a customer id",
            ],
            "The download is blocked by the DLP rule and the log shows it.",
            variants=[
                {
                    "name": "customer id",
                    "inputs": [{"name": "pattern", "value": "CUST-\\d{6}"}],
                    "expected": "blocked",
                }
            ],
        ),
        "test_files_dlp_rule_enforced",
    ),
    "method": (
        _draft(
            "X-3",
            "The safe viewer lists the members of an encrypted archive after unlocking",
            [
                "Download an encrypted zip archive and enter its password",
                "View the archive in the safe viewer",
            ],
            "The viewer is read-only and lists the archive's members.",
        ),
        "TestFilesArchives",
    ),
    "module": (
        _draft(
            "X-4",
            "Printing documents is blocked by the print policy",
            ["Set the print policy to block printing", "Open a document and print it"],
            "Printing is refused with a message.",
        ),
        None,
    ),
}


@pytest.mark.parametrize("kind", list(SCENARIOS))
def test_decision_kinds(setup: tuple[Settings, IndexData], kind: str) -> None:
    settings, index = setup
    draft, target = SCENARIOS[kind]
    ticket = Ticket(
        id=draft.ticket_id,
        title=draft.intent,
        description=" ".join(draft.steps) + " " + draft.expected_outcome,
        source=SourceInfo(system="jira", ref=draft.ticket_id),
    )
    retrieval = retrieve(ticket, index, settings, None, draft)
    choice = choose_domain(retrieval, index, settings, ticket, draft)
    decision = decide(draft, retrieval, index, settings, choice)
    assert decision.domain == "files"
    assert decision.kind == kind, decision.reasons
    if kind == "covered":
        assert decision.test_id == "test_files_download_type_action[exe]"
    if kind in ("covered", "variant"):
        assert decision.target is not None and decision.target.endswith(f".{target}")
    if kind == "method":
        assert decision.target == target
    if kind == "module":  # the scaffold still comes from a sibling of the same test kind
        assert decision.target is not None and decision.target.startswith("TestFiles")


def test_a_case_is_named_only_with_its_argument_in_context(
    setup: tuple[Settings, IndexData],
) -> None:
    _settings, index = setup
    chunk = next(c for c in index.chunks if c.symbol_name == "test_files_download_type_action")
    assert _named_case(chunk, {"exe", "file", "block"}) == "exe"
    assert _named_case(chunk, {"exe", "block"}) is None  # "exe" without "file"/"type"
    dlp = next(c for c in index.chunks if c.symbol_name == "test_files_dlp_rule_enforced")
    assert _named_case(dlp, {"print", "policy", "block"}) is None
    assert _named_case(dlp, {"rule", "action", "block"}) == "block"


def test_a_domain_without_tests_means_a_new_module(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    draft = SCENARIOS["module"][0]
    empty = DomainChoice(Domain("printing", ("tests/printing",)), {"printing": 1.0})
    decision = decide(draft, _empty_retrieval(), index, settings, empty)
    assert decision.kind == "module" and decision.target is None
    assert "no tests in the domain" in decision.reasons[-1]


def test_a_named_value_alone_never_means_covered(setup: tuple[Settings, IndexData]) -> None:
    """Step-7 eval: with the pagination test left out, a page-2 draft that names ``allow``
    was "covered" by the filter test. Covered now needs the words to match on their own."""
    from ticket2test.eval.generation import index_without

    settings, index = setup
    pagination = next(c.id for c in index.chunks if c.symbol_name == "test_rules_list_pagination")
    used = index_without(index, {pagination})
    draft = _draft(
        "X-6",
        "Page 2 of the rule list filtered by the allow action shows only allow rules",
        ["Filter the rule list by the allow action", "Go to the next page"],
        "Page 2 shows only allow rules and the allow filter stays selected.",
    ).model_copy(update={"markers": _draft("X", "", [], "").markers.model_copy(
        update={"component": "rules"})})  # fmt: skip
    ticket = Ticket(
        id="X-6", title=draft.intent, description=" ".join(draft.steps),
        source=SourceInfo(system="jira", ref="X-6"),
    )  # fmt: skip
    retrieval = retrieve(ticket, used, settings, None, draft)
    decision = decide(draft, retrieval, used, settings, choose_domain(retrieval, used, settings))
    assert decision.kind != "covered", decision.reasons
    filter_test = next(c for c in decision.candidates if c.test == "test_rules_list_filter_action")
    assert filter_test.matched_param == "allow"  # named, and still not enough


def test_the_tickets_component_routes_it(setup: tuple[Settings, IndexData]) -> None:
    """Step-7 eval: retrieval and the draft's broad component pointed elsewhere, while the
    ticket's own component named the right folder. In `generate` the ticket itself isn't
    there, so its components travel in the retrieval result."""
    settings, index = setup
    retrieval = _empty_retrieval().model_copy(update={"ticket_components": ["Tenants"]})
    choice = choose_domain(retrieval, index, settings)
    assert choice.domain is not None and choice.domain.name == "tenants"
    assert not choice.uncertain and "component" in choice.reason
    two = retrieval.model_copy(update={"ticket_components": ["tenants", "rules"]})
    assert "component" not in choose_domain(two, index, settings).reason  # not one: scored


def test_domain_names_match_stemmed_words(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    draft = SCENARIOS["module"][0].model_copy(
        update={"markers": SCENARIOS["module"][0].markers.model_copy(
            update={"component": "file download"})}
    )  # fmt: skip
    choice = choose_domain(_empty_retrieval(), index, settings, None, draft)
    assert choice.domain is not None and choice.domain.name == "files"  # "file" ~ "files"


def test_a_class_named_after_the_draft_gets_the_method(setup: tuple[Settings, IndexData]) -> None:
    """Eval on the browser-limit tickets: with its own test left out, a draft about the limit
    scored 0.39 against TestAgentBrowserLimit (bar 0.40) and became a duplicate module."""
    from ticket2test.eval.generation import index_without

    settings, index = setup
    refused = {c.id for c in index.chunks if c.symbol_name == "test_agent_browser_limit_refused"}
    used = index_without(index, refused)
    draft = _draft(
        "X-7",
        "A fourth agent browser session is refused at a browser limit of three",
        ["Open three agent browser sessions", "Open a fourth"],
        "The fourth attempt gets 429 before the upgrade.",
        test_kind="api",
    ).model_copy(update={"markers": _draft("X", "", [], "").markers.model_copy(
        update={"component": "agent"})})  # fmt: skip
    ticket = Ticket(
        id="X-7", title=draft.intent, description=" ".join(draft.steps),
        components=["agent"], source=SourceInfo(system="jira", ref="X-7"),
    )  # fmt: skip
    retrieval = retrieve(ticket, used, settings, None, draft)
    decision = decide(draft, retrieval, used, settings, choose_domain(retrieval, used, settings))
    assert (decision.kind, decision.target) == ("method", "TestAgentBrowserLimit"), decision.reasons
    assert "named after" in decision.reasons[-1]


# --- placement rules (v6 dev-set findings) --------------------------------------------------


def test_deployment_gates_are_read_from_class_decorators(setup: tuple[Settings, IndexData]) -> None:
    from ticket2test.generate.reuse import _deployment_gate

    settings, _ = setup
    deployments = ["cloud", "on_prem"]
    skipif = 'pytest.mark.skipif(CONFIG.deployment != "cloud", reason="cloud-only test")'
    assert _deployment_gate([skipif], deployments, settings) == {"cloud"}
    equal = 'pytest.mark.skipif(CONFIG.deployment == "cloud", reason="x")'
    assert _deployment_gate([equal], deployments, settings) == {"on_prem"}
    both = 'environments("cloud", "on_prem")'
    assert _deployment_gate([both], deployments, settings) == {"cloud", "on_prem"}
    assert _deployment_gate(['environments("on_prem")'], deployments, settings) == {"on_prem"}
    assert _deployment_gate(["cloud_only"], deployments, settings) == {"cloud"}
    assert _deployment_gate(['browsers("chrome")'], deployments, settings) is None


EXCEPTIONS = DomainChoice(domain=Domain("exceptions", ("tests/exceptions",)), reason="test")


def _listing_draft() -> TestCaseDraft:
    return _draft(
        "X-1",
        "The exception list shows the names of the existing exceptions",
        ["Have exceptions a and b", "Open Exceptions"],
        "The list shows the exception names a and b",
        markers={"priority": "p3", "component": "exceptions", "suite": "regression"},
    )


def test_a_test_never_goes_into_a_narrower_gated_class(setup: tuple[Settings, IndexData]) -> None:
    """Dev-set finding: a general list test went into a cloud-only legacy class, so it would
    never run on-prem."""
    settings, index = setup
    decision = decide(_listing_draft(), _empty_retrieval(), index, settings, EXCEPTIONS)
    assert decision.target not in ("TestExceptionsLegacyList", "TestExceptionsLegacyEditor")
    assert any(
        r.startswith("not TestExceptionsLegacyList: runs only on cloud") for r in decision.reasons
    ), decision.reasons
    cloud = _listing_draft().model_copy(update={"deployment_type": "cloud"})
    decision = decide(cloud, _empty_retrieval(), index, settings, EXCEPTIONS)
    assert not any("runs only on cloud" in r for r in decision.reasons)  # fits a cloud draft


def test_frozen_classes_are_skipped(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    frozen = settings.model_copy(
        update={
            "generate": settings.generate.model_copy(
                update={
                    "reuse": settings.generate.reuse.model_copy(
                        update={"frozen_classes": ["LegacyBrowserBase"]}
                    )
                }
            )
        }
    )
    cloud = _listing_draft().model_copy(update={"deployment_type": "cloud"})
    decision = decide(cloud, _empty_retrieval(), index, frozen, EXCEPTIONS)
    assert decision.target not in ("TestExceptionsLegacyList", "TestExceptionsLegacyEditor")
    assert any("frozen (LegacyBrowserBase" in r for r in decision.reasons), decision.reasons


def test_a_class_marked_with_the_tickets_components_is_preferred(
    setup: tuple[Settings, IndexData],
) -> None:
    """A cross-area ticket: the general class scores higher, but a class whose component marker
    names exactly the ticket's components (and still matches) gets the test, so the test carries
    the marker the suite selects cross-area tests by."""
    settings, index = setup
    draft = _draft(
        "X-2",
        "A new exception with a target is published",
        ["Click Add exception", "Enter a name and a target", "Save the exception",
         "Save and publish"],
        "The published policy has the exception with its target",
        markers={"priority": "p2", "component": "exceptions", "suite": "regression"},
    )  # fmt: skip
    plain = decide(draft, _empty_retrieval(), index, settings, EXCEPTIONS)
    assert plain.target == "TestExceptions"  # the best match on its own
    cross = _empty_retrieval().model_copy(update={"ticket_components": ["exceptions", "rules"]})
    decision = decide(draft, cross, index, settings, EXCEPTIONS)
    assert decision.kind == "method" and decision.target == "TestExceptionsRules", decision.reasons
    assert any("component marker matches" in r for r in decision.reasons)


def test_a_cross_area_ticket_goes_to_the_area_marked_with_its_components(
    setup: tuple[Settings, IndexData],
) -> None:
    settings, index = setup
    retrieval = _empty_retrieval().model_copy(update={"ticket_components": ["exceptions", "rules"]})
    choice = choose_domain(retrieval, index, settings)
    assert choice.domain is not None and choice.domain.name == "exceptions"
    assert "marked with the ticket's components" in choice.reason and not choice.uncertain


def test_an_uncertain_area_never_patches_an_existing_test(
    setup: tuple[Settings, IndexData],
) -> None:
    """Dev-set finding: with the area in doubt, a cross-area ticket became a new case of a test
    in the wrong area."""
    from tests.test_patch import _ticketed

    settings, index = setup
    draft = SCENARIOS["covered"][0]
    retrieval = _ticketed(settings, index, draft)
    sure = choose_domain(retrieval, index, settings)
    assert decide(draft, retrieval, index, settings, sure).kind == "covered"
    unsure = DomainChoice(domain=sure.domain, uncertain=True, reason="close call")
    decision = decide(draft, retrieval, index, settings, unsure)
    assert decision.kind not in ("covered", "variant")
    assert any("area uncertain" in r for r in decision.reasons)
