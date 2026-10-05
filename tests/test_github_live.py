"""Live check against the real GitHub API. Skipped by default; run with `pytest -m live`."""

from __future__ import annotations

import pytest

from ticket2test.adapters.tickets.github import GitHubIssueSource
from ticket2test.normalize import normalize


@pytest.mark.live
def test_fetch_and_normalize_real_issue() -> None:
    ticket = normalize(GitHubIssueSource().fetch("encode/httpx#1482"))
    assert ticket.title.startswith("Too much data for declared Content-Length")
    assert ticket.expected is not None
    assert ticket.steps_to_reproduce
