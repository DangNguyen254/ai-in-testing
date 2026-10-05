"""GitHubIssueSource against an in-memory transport. No network."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from tests.conftest import load_github_fixture
from ticket2test.adapters.tickets.base import RateLimitError, TicketNotFoundError, TicketSourceError
from ticket2test.adapters.tickets.github import GitHubIssueSource, is_github_ref, parse_ref
from ticket2test.config import GitHubSettings

Handler = Callable[[httpx.Request], httpx.Response]


def _source(handler: Handler, token: str | None = "", **settings: int) -> GitHubIssueSource:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GitHubIssueSource(GitHubSettings(**settings), token=token, client=client)


def _fixture_handler(number: int, seen: list[httpx.Request] | None = None) -> Handler:
    issue, comments = load_github_fixture(number)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path == f"/repos/encode/httpx/issues/{number}":
            return httpx.Response(200, json=issue)
        if path == f"/repos/encode/httpx/issues/{number}/comments":
            per_page = int(request.url.params["per_page"])
            page = int(request.url.params["page"])
            return httpx.Response(200, json=comments[(page - 1) * per_page : page * per_page])
        return httpx.Response(404, json={"message": "Not Found"})

    return handler


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("encode/httpx#1482", ("encode", "httpx", 1482)),
        (" encode/httpx#7 ", ("encode", "httpx", 7)),
        ("https://github.com/encode/httpx/issues/1482", ("encode", "httpx", 1482)),
        ("https://github.com/pydantic/pydantic-core/issues/12/", ("pydantic", "pydantic-core", 12)),
    ],
)
def test_parse_ref(ref: str, expected: tuple[str, str, int]) -> None:
    assert parse_ref(ref) == expected
    assert is_github_ref(ref)


@pytest.mark.parametrize(
    "ref", ["encode/httpx", "httpx#12", "DEMO-1", "https://github.com/encode/httpx/pull/12", ""]
)
def test_parse_ref_rejects_non_issue_refs(ref: str) -> None:
    assert not is_github_ref(ref)
    with pytest.raises(ValueError):
        parse_ref(ref)


def test_fetch_returns_issue_and_all_comments() -> None:
    raw = _source(_fixture_handler(1234)).fetch("encode/httpx#1234")
    assert raw.source == "github"
    assert raw.ref == "encode/httpx#1234"
    assert raw.payload["issue"]["number"] == 1234
    assert len(raw.payload["comments"]) == 9
    assert raw.payload["comments_complete"] is True


def test_comments_are_paginated() -> None:
    seen: list[httpx.Request] = []
    raw = _source(_fixture_handler(914, seen), comments_per_page=10).fetch("encode/httpx#914")
    assert len(raw.payload["comments"]) == 43
    assert raw.payload["comments_complete"] is True
    comment_pages = [r for r in seen if r.url.path.endswith("/comments")]
    assert [int(r.url.params["page"]) for r in comment_pages] == [1, 2, 3, 4, 5]


def test_comment_pages_are_capped() -> None:
    seen: list[httpx.Request] = []
    source = _source(_fixture_handler(914, seen), comments_per_page=10, max_comment_pages=2)
    raw = source.fetch("encode/httpx#914")
    assert len(raw.payload["comments"]) == 20
    assert raw.payload["comments_complete"] is False
    assert len([r for r in seen if r.url.path.endswith("/comments")]) == 2


def test_no_auth_header_without_token() -> None:
    seen: list[httpx.Request] = []
    _source(_fixture_handler(2985, seen), token=None).fetch("encode/httpx#2985")
    assert all("authorization" not in r.headers for r in seen)


def test_token_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-value")
    seen: list[httpx.Request] = []
    _source(_fixture_handler(2985, seen), token=None).fetch("encode/httpx#2985")
    assert seen and all(r.headers["authorization"] == "Bearer test-token-value" for r in seen)


def test_not_found() -> None:
    with pytest.raises(TicketNotFoundError, match="not found"):
        _source(_fixture_handler(2985)).fetch("encode/httpx#999999")


def test_pull_request_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"number": 5, "title": "PR", "pull_request": {}})

    with pytest.raises(TicketSourceError, match="pull request"):
        _source(handler).fetch("encode/httpx#5")


def test_primary_rate_limit_message_has_reset_time_and_token_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1767225600"},
            json={"message": "API rate limit exceeded"},
        )

    with pytest.raises(RateLimitError) as info:
        _source(handler, token=None).fetch("encode/httpx#1")
    message = str(info.value)
    assert "rate limit" in message
    assert "2026-01-01 00:00:00 UTC" in message
    assert "GITHUB_TOKEN" in message


def test_secondary_rate_limit_uses_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "60"}, json={"message": "slow down"})

    with pytest.raises(RateLimitError, match="Retry after 60 seconds"):
        _source(handler, token="t").fetch("encode/httpx#1")


def test_plain_403_is_not_reported_as_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"})

    with pytest.raises(TicketSourceError) as info:
        _source(handler).fetch("encode/httpx#1")
    assert not isinstance(info.value, RateLimitError)


def test_bad_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(TicketSourceError, match="rejected the token"):
        _source(handler, token="bad").fetch("encode/httpx#1")


def test_network_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(TicketSourceError, match="Network error"):
        _source(handler).fetch("encode/httpx#1")
