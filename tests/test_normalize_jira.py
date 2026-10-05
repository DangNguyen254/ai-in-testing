"""Jira export stub + normalization, on hand-written fake data."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.conftest import FIXTURES
from ticket2test.adapters.tickets.base import TicketNotFoundError, TicketSourceError
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.config import Settings
from ticket2test.normalize import normalize

ADF = FIXTURES / "jira" / "adf_issue.json"
WIKI = FIXTURES / "jira" / "wiki_export.json"


def test_adf_issue_normalizes() -> None:
    ticket = normalize(JiraExportSource(ADF).fetch("DEMO-101"))

    assert ticket.id == "DEMO-101"
    assert ticket.title == "Redirect drops query string when Location header is relative"
    assert ticket.labels == ["regression", "http-client"]
    assert ticket.components == ["redirects", "url-parsing"]
    assert ticket.source.system == "jira"
    assert ticket.source.url == "https://jira.example.com/browse/DEMO-101"
    assert ticket.steps_to_reproduce == [
        "Start the demo server on port 8080.",
        "Request /old?page=2 with redirects enabled.",
        "Inspect the final request URL.",
        '```python\nclient = Client(follow_redirects=True)\nresp = client.get("http://localhost:8080/old?page=2")\nprint(resp.url)\n```',
    ]
    assert ticket.expected == "Final URL is http://localhost:8080/new?page=2"
    assert ticket.actual == "Final URL is http://localhost:8080/new\nThe query string is gone."
    assert ticket.description is not None
    assert "Location header loses the original query string" in ticket.description
    assert "Library version 1.2.3" in ticket.description
    assert ticket.links == [
        "https://www.rfc-editor.org/rfc/rfc9110",
        "https://jira.example.com/browse/DEMO-42",
        "https://jira.example.com/browse/DEMO-7",
    ]
    assert [c.author for c in ticket.comments] == ["Alex Example", "Sam Sample"]
    assert ticket.comments[0].body == "@Sam Sample confirmed on main."
    assert ticket.comments[0].created_at == datetime(2026, 1, 15, 10, 30, tzinfo=UTC)
    assert ticket.comments_omitted == 0


def test_wiki_markup_issue_from_search_export() -> None:
    ticket = normalize(JiraExportSource(WIKI).fetch("DEMO-202"))

    assert ticket.title == "Timeout setting ignored for streaming downloads"
    assert ticket.components == ["streaming"]
    assert ticket.steps_to_reproduce == [
        "Create a client with timeout=1",
        "Stream a slow endpoint (https://slow.example.com/drip)",
        "Wait",
        '```python\nwith client.stream("GET", url) as r:\n'
        "    for chunk in r.iter_bytes():\n        pass\n```",
    ]
    assert ticket.expected == "A timeout error after about 1 second."
    assert ticket.actual == "The download hangs for minutes."
    assert ticket.links == ["https://slow.example.com/drip"]
    assert ticket.comments == []


def test_issue_without_sections_has_empty_fields() -> None:
    ticket = normalize(JiraExportSource(WIKI).fetch("DEMO-203"))
    assert ticket.description == "Cookies persist after calling clear()."
    assert ticket.steps_to_reproduce == []
    assert ticket.expected is None
    assert ticket.actual is None
    assert ticket.components == []
    assert ticket.comments[0].body == "Seen on 2.x as well."


def test_custom_field_map_overrides_description_sections() -> None:
    settings = Settings.model_validate(
        {
            "tickets": {
                "jira": {
                    "browse_url": "https://tickets.example.org/browse/",
                    "field_map": {
                        "steps_to_reproduce": "customfield_10050",
                        "expected": "customfield_10051",
                    },
                }
            }
        }
    )
    ticket = normalize(JiraExportSource(WIKI).fetch("DEMO-203"), settings)
    assert ticket.steps_to_reproduce == ["Open a session", "Call clear()", "Inspect the jar"]
    assert ticket.expected == "The jar is empty."
    assert ticket.actual is None
    assert ticket.source.url == "https://tickets.example.org/browse/DEMO-203"


def test_empty_custom_field_falls_back_to_description() -> None:
    settings = Settings.model_validate(
        {"tickets": {"jira": {"field_map": {"steps_to_reproduce": "customfield_10050"}}}}
    )
    ticket = normalize(JiraExportSource(WIKI).fetch("DEMO-202"), settings)  # field is null
    assert ticket.steps_to_reproduce[0] == "Create a client with timeout=1"


def test_unknown_key() -> None:
    with pytest.raises(TicketNotFoundError):
        JiraExportSource(WIKI).fetch("DEMO-999")


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TicketSourceError, match="not found"):
        JiraExportSource(tmp_path / "nope.json").fetch("DEMO-1")


def test_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(TicketSourceError, match="not valid JSON"):
        JiraExportSource(bad).fetch("DEMO-1")


def test_plain_list_export(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text('[{"key": "X-1", "fields": {"summary": "S"}}]', encoding="utf-8")
    ticket = normalize(JiraExportSource(path).fetch("X-1"))
    assert ticket.title == "S"
    assert ticket.description is None
    assert ticket.source.url is None  # no browse_url and no "self" link
