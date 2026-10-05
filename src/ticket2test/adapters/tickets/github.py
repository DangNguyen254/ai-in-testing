"""GitHub Issues ticket source (REST API v3)."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from ticket2test.adapters.tickets.base import (
    RateLimitError,
    RawTicket,
    TicketNotFoundError,
    TicketSource,
    TicketSourceError,
)
from ticket2test.config import GitHubSettings

TOKEN_ENV_VAR = "GITHUB_TOKEN"

_SHORT_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")
_URL_REF = re.compile(
    r"^https?://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/issues/(?P<number>\d+)/?$"
)


def parse_ref(ref: str) -> tuple[str, str, int]:
    """Parse ``owner/repo#123`` or an issue URL into (owner, repo, number)."""
    ref = ref.strip()
    match = _SHORT_REF.match(ref) or _URL_REF.match(ref)
    if not match:
        raise ValueError(
            f"Not a GitHub issue reference: {ref!r} "
            "(expected 'owner/repo#123' or 'https://github.com/owner/repo/issues/123')"
        )
    return match["owner"], match["repo"], int(match["number"])


def is_github_ref(ref: str) -> bool:
    try:
        parse_ref(ref)
    except ValueError:
        return False
    return True


class GitHubIssueSource(TicketSource):
    """Fetches an issue and its comments.

    The token is optional (public repos work without one, at a lower rate limit) and is
    read from the ``GITHUB_TOKEN`` environment variable unless passed explicitly.

    Payload shape: ``{"issue": {...}, "comments": [...], "comments_complete": bool}``.
    """

    name = "github"

    def __init__(
        self,
        settings: GitHubSettings | None = None,
        token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings or GitHubSettings()
        token = token if token is not None else os.environ.get(TOKEN_ENV_VAR) or None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ticket2test",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._has_token = bool(token)
        self._client = client or httpx.Client(timeout=self._settings.timeout_seconds)
        self._headers = headers

    def fetch(self, ref: str) -> RawTicket:
        owner, repo, number = parse_ref(ref)
        base = f"{self._settings.api_url.rstrip('/')}/repos/{owner}/{repo}/issues/{number}"

        issue = self._get_json(base, ref)
        if not isinstance(issue, dict):
            raise TicketSourceError(f"Unexpected GitHub response for {ref}")
        if "pull_request" in issue:
            raise TicketSourceError(f"{ref} is a pull request, not an issue")

        comments, complete = self._fetch_comments(f"{base}/comments", ref)
        return RawTicket(
            source=self.name,
            ref=f"{owner}/{repo}#{number}",
            payload={"issue": issue, "comments": comments, "comments_complete": complete},
        )

    def _fetch_comments(self, url: str, ref: str) -> tuple[list[Any], bool]:
        comments: list[Any] = []
        per_page = self._settings.comments_per_page
        for page in range(1, self._settings.max_comment_pages + 1):
            batch = self._get_json(url, ref, params={"per_page": per_page, "page": page})
            if not isinstance(batch, list):
                raise TicketSourceError(f"Unexpected GitHub comments response for {ref}")
            comments.extend(batch)
            if len(batch) < per_page:
                return comments, True
        return comments, False  # page cap reached; more comments may exist

    def _get_json(self, url: str, ref: str, params: dict[str, int] | None = None) -> Any:
        try:
            response = self._client.get(url, headers=self._headers, params=params)
        except httpx.HTTPError as exc:
            raise TicketSourceError(f"Network error fetching {ref}: {exc}") from exc

        status = response.status_code
        if status == 200:
            return response.json()
        if status == 404:
            raise TicketNotFoundError(f"GitHub issue not found: {ref}")
        if status == 410:
            raise TicketNotFoundError(f"GitHub issue was deleted or transferred: {ref}")
        if status == 401:
            raise TicketSourceError(f"GitHub rejected the token ({TOKEN_ENV_VAR}) for {ref}")
        if status in (403, 429) and self._is_rate_limited(response):
            raise RateLimitError(self._rate_limit_message(response))
        raise TicketSourceError(f"GitHub returned HTTP {status} for {ref}")

    @staticmethod
    def _is_rate_limited(response: httpx.Response) -> bool:
        if response.status_code == 429:
            return True
        if response.headers.get("x-ratelimit-remaining") == "0":
            return True
        return "retry-after" in response.headers or "rate limit" in response.text.lower()

    def _rate_limit_message(self, response: httpx.Response) -> str:
        parts = ["GitHub API rate limit exceeded."]
        retry_after = response.headers.get("retry-after")
        reset = response.headers.get("x-ratelimit-reset")
        if retry_after and retry_after.isdigit():
            parts.append(f"Retry after {retry_after} seconds.")
        elif reset and reset.isdigit():
            when = datetime.fromtimestamp(int(reset), tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
            parts.append(f"Limit resets at {when}.")
        if not self._has_token:
            parts.append(f"Set {TOKEN_ENV_VAR} to get a higher limit.")
        return " ".join(parts)
