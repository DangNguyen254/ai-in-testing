"""The tracker-to-suite glossary: loading, matching tickets, logging what it lacks, and its use in
search and the area choice (docs/knowledge-plan.md, step C). Invented terms only."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import Settings
from ticket2test.generate.domain import choose_domain
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.knowledge import GlossaryError, load_glossary, match_terms, unknown_words
from ticket2test.knowledge.glossary import record_unmapped
from ticket2test.models.ticket import SourceInfo, Ticket
from ticket2test.retrieve.pipeline import retrieve

STANDIN = REPO_ROOT / "standin"

GLOSSARY = """\
version: 1
updated: 2026-10-29
terms:
  - term: "Asset Handover"
    kind: component
    status: proposed
    checked: 2026-10-29
    folders: [tests/files]
    classes: [tests/files/test_files_downloads.py::TestFilesDownloads]
    data:
      - key: decision
        values: [blocked, converted]
    note: downloads are the asset handover feature
    evidence: ["tests/files/test_files_downloads.py:1"]
    area: an old field the tool ignores
  - term: "safe download"
    kind: phrase
    folders: [tests/files]
  - term: "Gone Feature"
    kind: epic
    classes: [tests/gone/test_gone.py::TestGone]
unmapped:
  - term: "Release Train"
    kind: epic
    reason: a release bucket
"""


def _ticket(**fields: object) -> Ticket:
    base: dict[str, object] = {
        "id": "DEMO-9",
        "title": "Exported report is not delivered",
        "source": SourceInfo(system="jira", ref="DEMO-9"),
    }
    return Ticket.model_validate({**base, **fields})


@pytest.fixture()
def glossary_file(tmp_path: Path) -> Path:
    path = tmp_path / "glossary.yaml"
    path.write_text(GLOSSARY, encoding="utf-8")
    return path


def test_the_glossary_loads_and_matches_a_tickets_words(glossary_file: Path) -> None:
    glossary = load_glossary(glossary_file)
    assert glossary is not None and len(glossary.terms) == 3
    assert glossary.terms[0].checked == "2026-10-29"  # YAML dates read as text
    ticket = _ticket(
        components=["asset-handover"],  # spacing and case don't matter
        labels=["Story", "Release Train"],
        description="Epic: Gone Feature\nUsers expect a SAFE download of the report.",
    )
    names = [t.term for t in match_terms(ticket, glossary)]
    assert names == ["Asset Handover", "safe download", "Gone Feature"]
    assert unknown_words(ticket, glossary) == ["Story"]  # Release Train is listed as unmapped
    assert load_glossary(glossary_file.with_name("missing.yaml")) is None


def test_a_broken_glossary_is_reported(tmp_path: Path) -> None:
    bad = tmp_path / "glossary.yaml"
    bad.write_text("terms: [ {term: x, kind: nonsense} ]\n", encoding="utf-8")
    with pytest.raises(GlossaryError):
        load_glossary(bad)


def test_unmapped_words_are_logged_once(tmp_path: Path) -> None:
    log = tmp_path / "glossary-unmapped.txt"
    record_unmapped(log, "DEMO-1", ["Story"], ["X: folder gone"], today="2026-10-30")
    record_unmapped(log, "DEMO-2", ["story", "New Thing"], [], today="2026-10-30")
    assert log.read_text(encoding="utf-8").splitlines() == [
        "unknown\tStory\tDEMO-1\t2026-10-30",
        "stale\tX: folder gone\tDEMO-1\t2026-10-30",
        "unknown\tNew Thing\tDEMO-2\t2026-10-30",
    ]


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("cache"))}}
    )
    data, _, _ = update_index(STANDIN, settings)
    return data


def test_the_glossary_steers_search_and_the_area_choice(
    index: IndexData, glossary_file: Path, tmp_path: Path
) -> None:
    """A ticket in the tracker's words only: its component names no folder, its text no code."""
    ticket = _ticket(
        title="Partner handover breaks after the upgrade",
        components=["Asset Handover"],
        labels=["Story"],
    )
    plain = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "c1")}})
    with_glossary = Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "c2")},
            "knowledge": {"glossary": str(glossary_file)},
        }
    )
    before = retrieve(ticket, index, plain)
    assert before.glossary_terms == []
    after = retrieve(ticket, index, with_glossary)
    assert after.glossary_terms == ["Asset Handover"]
    assert after.glossary_folders == ["tests/files"]
    assert any(h.file_path.startswith("tests/files/") for h in after.hits[:3])
    # the ticket's words found nothing there, so the glossary's words were searched as well
    assert any(r.detail.startswith("query=glossary") for h in after.hits for r in h.reasons)
    choice = choose_domain(after, index, with_glossary, ticket)
    assert choice.domain is not None and choice.domain.name == "files"
    assert "glossary" in choice.reason and not choice.uncertain
    unmapped = (tmp_path / "glossary-unmapped.txt").read_text(encoding="utf-8")
    assert "unknown\tStory\tDEMO-9" in unmapped


def test_a_mapped_name_the_suite_no_longer_has_is_logged_as_stale(
    index: IndexData, glossary_file: Path, tmp_path: Path
) -> None:
    settings = Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "c")},
            "knowledge": {"glossary": str(glossary_file)},
        }
    )
    retrieve(_ticket(labels=["Gone Feature"]), index, settings)
    unmapped = (tmp_path / "glossary-unmapped.txt").read_text(encoding="utf-8")
    assert "stale\tGone Feature: class tests/gone/test_gone.py::TestGone" in unmapped


def test_when_the_tickets_words_find_the_place_the_glossary_only_reorders(
    index: IndexData, glossary_file: Path, tmp_path: Path
) -> None:
    """Found on the real suite: added glossary results crowded out the exact test the ticket's
    own words had found. With words that already reach a mapped place, nothing is added: results
    there are lifted in the ranking."""
    ticket = _ticket(
        title="An executable download is blocked by the download policy",
        components=["Asset Handover"],
    )
    settings = Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "c")},
            "knowledge": {"glossary": str(glossary_file)},
        }
    )
    result = retrieve(ticket, index, settings)
    assert not any(r.detail.startswith("query=glossary") for h in result.hits for r in h.reasons)
    lifted = [h for h in result.hits if "glossary" in h.rank_features]
    assert lifted and all(h.file_path.startswith("tests/files/") for h in lifted)
