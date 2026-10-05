"""Normalization of 5 real public encode/httpx issues (raw API JSON fixtures)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from tests.conftest import GITHUB_FIXTURE_ISSUES, github_raw, load_github_fixture
from ticket2test.adapters.tickets.base import RawTicket
from ticket2test.config import NormalizeSettings, Settings
from ticket2test.normalize import NormalizationError, normalize


@pytest.mark.parametrize("number", GITHUB_FIXTURE_ISSUES)
def test_common_fields(number: int) -> None:
    issue, comments = load_github_fixture(number)
    ticket = normalize(github_raw(number))

    assert ticket.id == f"encode/httpx#{number}"
    assert ticket.title == issue["title"]
    assert ticket.labels == [label["name"] for label in issue["labels"]]
    assert ticket.source.system == "github"
    assert ticket.source.url == f"https://github.com/encode/httpx/issues/{number}"
    assert len(ticket.comments) == len(comments) == issue["comments"]
    assert ticket.comments_omitted == 0
    assert ticket.components == []  # GitHub has no components unless configured
    assert ticket.source.url not in ticket.links
    assert ticket.description
    assert "<!--" not in ticket.description  # issue-template comments stripped


def test_2985_no_sections_means_empty_fields() -> None:
    ticket = normalize(github_raw(2985))
    assert ticket.steps_to_reproduce == []
    assert ticket.expected is None
    assert ticket.actual is None
    assert ticket.comments == []
    assert ticket.links == ["https://github.com/encode/httpx/discussions/2984"]
    assert ticket.description is not None
    assert "unescaped in a URL userinfo/authority section" in ticket.description
    assert "`" not in ticket.description  # inline code markers removed


def test_1482_full_template() -> None:
    ticket = normalize(github_raw(1482))
    assert len(ticket.steps_to_reproduce) == 1
    step = ticket.steps_to_reproduce[0]
    assert step.startswith("```") and step.endswith("```")
    assert "files={" in step and "'upload-file'" in step
    assert ticket.expected == "An exception not be raised and the content length properly computed"
    assert ticket.actual == "An exception is raised."
    assert ticket.description is not None
    assert "### " not in ticket.description  # headings become plain lines
    assert "-->" not in ticket.description  # orphaned template comment marker dropped
    assert ticket.comments[0].author is not None
    assert ticket.comments[0].created_at is not None


def test_1498_code_steps_and_multi_paragraph_expected() -> None:
    ticket = normalize(github_raw(1498))
    steps = ticket.steps_to_reproduce
    assert len(steps) == 3
    assert 'httpx.Client(base_url="https://example.org/some/path")' in steps[0]
    assert steps[1] == "also, calling the get method leads to the following exception:"
    assert "UnsupportedProtocol" in steps[2]
    assert ticket.expected == (
        'client.build_request("POST", "/sub:path") returns '
        "<Request('POST', 'https://example.org/some/path/sub%3Apath')>\n\n"
        'client.get("/sub:path") not raises UnsupportedProtocol exception'
    )
    assert ticket.actual is not None
    assert "returns <Request('POST', 'sub:path')>" in ticket.actual
    # "#1407" in a comment resolves to a repo issue URL; URLs inside inline code are not links.
    assert "https://github.com/encode/httpx/issues/1407" in ticket.links
    assert not any("example.org" in link for link in ticket.links)


def test_1234_free_form_bug_report_has_no_invented_sections() -> None:
    ticket = normalize(github_raw(1234))
    assert ticket.steps_to_reproduce == []
    assert ticket.expected is None
    assert ticket.actual is None
    assert ticket.description is not None
    assert "WWW-Authenticate: Digest" in ticket.description  # code block kept verbatim
    assert len(ticket.comments) == 9


def test_914_steps_external_links_and_long_thread() -> None:
    ticket = normalize(github_raw(914))
    assert len(ticket.steps_to_reproduce) == 2
    assert "asyncio.run(main())" in ticket.steps_to_reproduce[0]
    assert ticket.steps_to_reproduce[1].startswith("Inserting time.sleep(0.1)")
    assert ticket.links[:2] == [
        "https://github.com/aio-libs/aiohttp/issues/4324",
        "https://github.com/aio-libs/aiohttp/issues/1925",
    ]
    assert len(ticket.comments) == 43
    times = [c.created_at for c in ticket.comments]
    assert all(t is not None for t in times)
    assert times == sorted(times)  # type: ignore[type-var]


# --- Edge cases ------------------------------------------------------------------------------


def _raw_with(
    issue_changes: dict[str, object], comments: list[dict[str, object]] | None = None
) -> RawTicket:
    issue, real_comments = load_github_fixture(1482)
    issue = copy.deepcopy(issue)
    issue.update(issue_changes)
    used = real_comments if comments is None else comments
    return RawTicket(
        source="github",
        ref="encode/httpx#1482",
        payload={"issue": issue, "comments": used, "comments_complete": True},
    )


@pytest.mark.parametrize("body", [None, "", "   \n\n  "])
def test_missing_description(body: str | None) -> None:
    ticket = normalize(_raw_with({"body": body}))
    assert ticket.description is None
    assert ticket.steps_to_reproduce == []
    assert ticket.expected is None
    assert ticket.actual is None
    assert ticket.title  # title still present


def test_no_steps_section() -> None:
    body = "### Describe the bug\nIt breaks.\n\n### Expected behavior\nIt works."
    ticket = normalize(_raw_with({"body": body}))
    assert ticket.steps_to_reproduce == []
    assert ticket.expected == "It works."
    assert ticket.actual is None


def test_missing_title_is_an_error() -> None:
    with pytest.raises(NormalizationError, match="no title"):
        normalize(_raw_with({"title": "  "}))


def _comment(i: int) -> dict[str, object]:
    return {
        "user": {"login": f"user{i}"},
        "body": f"comment number {i}",
        "created_at": datetime(2020, 1, 1, tzinfo=UTC).replace(minute=i % 60).isoformat(),
    }


def test_very_long_comment_thread_keeps_first_and_latest() -> None:
    comments = [_comment(i) for i in range(250)]
    settings = Settings(normalize=NormalizeSettings(max_comments=10))
    ticket = normalize(_raw_with({"comments": 250}, comments), settings)

    assert len(ticket.comments) == 10
    assert ticket.comments_omitted == 240
    bodies = [c.body for c in ticket.comments]
    assert bodies[:5] == [f"comment number {i}" for i in range(5)]
    assert bodies[5:] == [f"comment number {i}" for i in range(245, 250)]


def test_comment_count_beyond_fetched_pages_is_reported_as_omitted() -> None:
    # The API said 500 comments exist, but the page cap meant only 3 were fetched.
    ticket = normalize(_raw_with({"comments": 500}, [_comment(i) for i in range(3)]))
    assert len(ticket.comments) == 3
    assert ticket.comments_omitted == 497


def test_very_long_comment_is_truncated_at_a_line_boundary() -> None:
    long_body = "\n".join(f"line {i} " + "x" * 50 for i in range(500))
    comments = [{"user": {"login": "u"}, "body": long_body, "created_at": None}]
    settings = Settings(normalize=NormalizeSettings(max_comment_chars=1000))
    ticket = normalize(_raw_with({"comments": 1}, comments), settings)

    body = ticket.comments[0].body
    assert len(body) < 1100
    assert body.splitlines()[-1].startswith("[... truncated ")
    assert all(line.startswith("line ") for line in body.splitlines()[:-1])


def test_component_label_prefixes() -> None:
    labels = [{"name": "component: url"}, {"name": "bug"}, {"name": "component:"}]
    settings = Settings.model_validate(
        {"tickets": {"github": {"component_label_prefixes": ["component:"]}}}
    )
    ticket = normalize(_raw_with({"labels": labels}), settings)
    assert ticket.components == ["url"]
    assert ticket.labels == ["component: url", "bug", "component:"]
