"""Test shapes (kind + action) and template ranking by shape."""

from __future__ import annotations

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.ticket import SourceInfo, Ticket
from ticket2test.retrieve.pipeline import retrieve
from ticket2test.retrieve.shape import Shape, shape_of_draft, shape_of_test

STANDIN = REPO_ROOT / "standin"


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("cache"))}}
    )
    index, _, _ = update_index(STANDIN, settings)
    return settings, index


def _draft(intent: str, steps: list[str], kind: str = "ui") -> TestCaseDraft:
    return TestCaseDraft.model_validate(
        {
            "id": "X/d1",
            "ticket_id": "X",
            "kind": "primary",
            "intent": intent,
            "markers": {"priority": "p2", "component": "rules", "suite": "regression"},
            "test_kind": kind,
            "deployment_type": "both",
            "preconditions": [],
            "steps": steps,
            "expected_outcome": "It works.",
            "variants": [],
            "confidence": 0.9,
            "prompt_version": "x",
        }
    )


@pytest.mark.parametrize(
    ("name", "shape"),
    [
        ("test_rules_add_basic", Shape("ui", "add")),
        ("test_rules_edit_action", Shape("ui", "edit")),
        ("test_rules_delete_several", Shape("ui", "delete")),
        ("test_rules_list_search", Shape("ui", "other")),
        ("test_settings_capabilities_enable_bulk", Shape("ui", "edit")),  # not "bulk_delete"
        ("test_policy_api_rules_update_forbidden", Shape("api", "edit")),
        ("test_agent_api_unknown_page", Shape("api", "other")),
    ],
)
def test_shapes_of_tests(setup: tuple[Settings, IndexData], name: str, shape: Shape) -> None:
    settings, index = setup
    chunk = next(c for c in index.chunks if c.symbol_name == name and not c.inherited_from)
    assert shape_of_test(chunk, settings) == shape


def test_shapes_of_drafts(setup: tuple[Settings, IndexData]) -> None:
    settings, _ = setup
    assert shape_of_draft(_draft("Deleted rules stay deleted", []), settings).action == "delete"
    assert shape_of_draft(_draft("Rule names", ["Adding a rule"]), settings).action == "add"
    assert (
        shape_of_draft(_draft("Search shows matches", ["Type a word"]), settings).action == "other"
    )
    hybrid = shape_of_draft(_draft("Change a rule", [], kind="hybrid"), settings)
    assert hybrid.distance(Shape("api", "edit")) == (0, 0)
    assert hybrid.distance(Shape("ui", "add")) == (0, 1)
    assert Shape("ui", "add").distance(Shape("api", "add")) == (1, 0)


@pytest.mark.parametrize(
    ("intent", "steps", "action"),
    [
        ("Deleting one rule keeps the others", ["Seed rules", "Delete one", "Publish"], "delete"),
        ("Editing a rule's action is published", ["Open the rule", "Change the action"], "edit"),
        ("A new rule is published", ["Add a rule", "Publish"], "add"),
    ],
)
def test_templates_follow_the_drafts_shape(
    setup: tuple[Settings, IndexData], intent: str, steps: list[str], action: str
) -> None:
    settings, index = setup
    draft = _draft(intent, steps)
    ticket = Ticket(
        id="X", title="Rules list", description="rules", source=SourceInfo(system="jira", ref="X")
    )
    result = retrieve(ticket, index, settings, None, draft)
    chunks = {c.id: c for c in index.chunks}
    first = chunks[result.templates[0].chunk_id]
    assert shape_of_test(first, settings) == Shape("ui", action), result.templates
    assert "same shape" in result.templates[0].why
