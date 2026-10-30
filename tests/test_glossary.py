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


@pytest.mark.parametrize(("status", "lift"), [("confirmed", 0.25), ("proposed", 0.1)])
def test_a_class_stands_for_its_folder_and_checked_entries_lift_more(
    index: IndexData, tmp_path: Path, status: str, lift: float
) -> None:
    """Found on the real suite: an entry naming one class lifted only that class, and the
    ticket's tests in a sibling class of the same feature dropped. An entry nobody checked yet
    may be wrong, so it lifts less."""
    glossary = tmp_path / "glossary.yaml"
    glossary.write_text(
        "terms:\n"
        "  - term: Asset Handover\n"
        f"    status: {status}\n"
        "    classes: [tests/files/test_files_downloads.py::TestFilesDownloads]\n",
        encoding="utf-8",
    )
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path / "c")}, "knowledge": {"glossary": str(glossary)}}
    )
    ticket = _ticket(
        title="A scanned file with a data leak rule is blocked", components=["Asset Handover"]
    )
    result = retrieve(ticket, index, settings)
    assert result.glossary_folders == ["tests/files"]
    lifted = {
        h.file_path: h.rank_features["glossary"]
        for h in result.hits
        if "glossary" in h.rank_features
    }
    assert any(not p.endswith("test_files_downloads.py") for p in lifted)  # the sibling classes
    assert set(lifted.values()) == {lift}


def test_in_a_folder_with_several_features_a_class_lifts_only_its_own(tmp_path: Path) -> None:
    """Found on the real suite: a class standing for its whole folder also lifted the other
    features' tests in a folder that holds several. A class stands for its feature: the tests
    sharing its component markers (sibling classes too), or itself when it has none."""
    repo = tmp_path / "repo"
    (repo / "tests" / "mixed").mkdir(parents=True)

    def test_file(name: str, cls: str, component: str | None) -> None:
        marker = f'@pytest.mark.component("{component}")\n' if component else ""
        (repo / "tests" / "mixed" / f"test_{name}.py").write_text(
            f"import pytest\n\n\n{marker}class {cls}:\n"
            f"    def test_{name}_report_export(self):\n        pass\n",
            encoding="utf-8",
        )

    test_file("alpha_one", "TestAlphaOne", "alpha")
    test_file("alpha_two", "TestAlphaTwo", "alpha")
    test_file("beta", "TestBeta", "beta")
    test_file("plain", "TestPlain", None)
    glossary = tmp_path / "glossary.yaml"
    glossary.write_text(
        "terms:\n"
        "  - term: Alpha Feature\n    status: confirmed\n"
        "    classes: [tests/mixed/test_alpha_one.py::TestAlphaOne]\n"
        "  - term: Plain Feature\n    status: confirmed\n"
        "    classes: [tests/mixed/test_plain.py::TestPlain]\n",
        encoding="utf-8",
    )
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path / "c")}, "knowledge": {"glossary": str(glossary)}}
    )
    index, _, _ = update_index(repo, settings)

    def lifted(component: str) -> set[str]:
        ticket = _ticket(title="The report export fails", components=[component])
        hits = retrieve(ticket, index, settings).hits
        return {
            Path(h.file_path).stem.removeprefix("test_")
            for h in hits
            if h.kind == "test" and "glossary" in h.rank_features
        }

    assert lifted("Alpha Feature") == {"alpha_one", "alpha_two"}  # its feature, not beta's
    assert lifted("Plain Feature") == {"plain"}  # no component markers: just the class


def test_the_draft_gets_the_suites_words_for_what_the_ticket_names(
    index: IndexData, tmp_path: Path
) -> None:
    """The draft runs before retrieval: the glossary terms the ticket names, and the known values
    of their areas from the suite map, translate the ticket's words into the suite's."""
    import json

    from ticket2test.draft import generate_drafts
    from ticket2test.llm import FakeLLMClient
    from ticket2test.suitemap import build_map, write_map

    glossary = tmp_path / "glossary.yaml"
    glossary.write_text(
        "terms:\n"
        "  - term: Rule Book\n    status: confirmed\n"
        "    folders: [tests/rules]\n    markers: [rules]\n"
        "    data:\n      - key: policy.rules[].action\n        values: [deny]\n",
        encoding="utf-8",
    )
    settings = Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "c")},
            "knowledge": {"glossary": str(glossary), "map_dir": str(tmp_path / "map")},
            "draft": {"skeleton": "never"},
        }
    )
    write_map(build_map(index, settings), tmp_path / "map", 10)
    item = {
        "kind": "primary",
        "intent": "A refused rule stays refused after publishing.",
        "markers": {"priority": "p2", "component": "Rules", "suite": "regression"},
        "test_kind": "ui",
        "deployment_type": "both",
        "preconditions": [],
        "steps": ["Add a rule that refuses traffic", "Publish"],
        "expected_outcome": "The rule's action is deny.",
        "variants": [],
    }
    reply = json.dumps({"status": "ok", "missing_info": [], "reason": "r", "drafts": [item]})
    fake = FakeLLMClient([reply])
    ticket = _ticket(
        title="A refused rule comes back allowed",
        components=["Rule Book"],
        description="Steps: add a refusing rule and publish. Expected: it stays refused.",
        steps_to_reproduce=["Add a refusing rule", "Publish"],
        expected="It stays refused.",
    )
    result = generate_drafts(ticket, fake, settings, provider="fake", model="m")
    prompt = fake.requests[0].messages[-1].content
    assert '- "Rule Book" in the suite: tested in tests/rules' in prompt
    assert "policy.rules[].action = deny" in prompt  # the glossary's value
    assert "  - policy.rules[].action: allow, deny, log" in prompt  # the area's known values
    assert "Allowed components: rules, unknown" in prompt  # the term's marker as the choice
    assert result.drafts[0].markers.component == "rules"
