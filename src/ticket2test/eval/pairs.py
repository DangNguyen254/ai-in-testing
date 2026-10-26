"""Eval pair sets: ticket <-> ground truth. Stored as IDs/URLs only; data is fetched on demand.

Ground truth kinds:
- ``fix_pr_files``: Python files changed by the ticket's fix PR (fetched from GitHub, cached)
- ``tests``: test functions linked to the ticket (e.g. the stand-in's ``manifest.json``)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ticket2test.adapters.tickets.base import RawTicket, TicketSourceError
from ticket2test.adapters.tickets.github import GitHubIssueSource
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.config import Settings


class ExpectedGap(BaseModel):
    """A piece the ticket needs that the suite lacks (a missing-piece ticket)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner: str  # a page-object chain ("nav.area.page") or a class name
    words: list[str] = Field(min_length=1)  # words the member's name contains (stemmed)


class EvalPair(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    ticket: str  # "owner/repo#123" or a Jira key
    ticket_url: str | None = None
    fix_pr: int | None = None
    fix_pr_url: str | None = None
    tests: list[str] = Field(default_factory=list)  # for ground_truth "tests": test function ids
    source: str | None = None  # provenance, e.g. "mined: <commit> code_skip"
    # What a correct run produces: a test (the default), a reported missing piece, insufficient
    # info (a vague ticket), or nothing because the ticket's area is legacy (out of scope).
    expect: Literal["test", "gap", "insufficient_info", "out_of_scope"] = "test"
    gaps: list[ExpectedGap] = Field(default_factory=list)


class PairSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str = ""
    repo_path: str  # relative to the project root
    repo_ref: str | None = None  # tag/commit the repo must be at
    repo_clone: str | None = None  # how to get it, for the error message
    ticket_source: Literal["github", "jira_export"]
    jira_export: str | None = None  # relative to the project root
    ground_truth: Literal["fix_pr_files", "tests"]
    conventions_doc: str | None = None  # relative to the project root; used by generation evals
    generation: bool = False  # also run the generation eval on this set (linked-test sets only)
    pairs: list[EvalPair]


def load_pair_set(path: Path) -> PairSet:
    return PairSet.model_validate_json(path.read_text(encoding="utf-8"))


class EvalCache:
    """Cache for data fetched on demand (git-ignored ``<cache_dir>/eval``)."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.root = settings.paths.cache_dir / "eval"
        self._settings = settings
        self._client = client

    def ticket_path(self, ref: str) -> Path:
        return self.root / "tickets" / f"{_safe(ref)}.json"

    def pr_files_path(self, owner_repo: str, number: int) -> Path:
        return self.root / "pr_files" / f"{_safe(owner_repo)}_{number}.json"

    def raw_ticket(self, pair_set: PairSet, pair: EvalPair, project_root: Path) -> RawTicket:
        if pair_set.ticket_source == "jira_export":
            assert pair_set.jira_export, "jira_export path missing in pair set"
            return JiraExportSource(project_root / pair_set.jira_export).fetch(pair.ticket)
        path = self.ticket_path(pair.ticket)
        if path.is_file():
            return RawTicket.model_validate_json(path.read_text(encoding="utf-8"))
        raw = GitHubIssueSource(self._settings.tickets.github, client=self._client).fetch(
            pair.ticket
        )
        self._write(path, raw.model_dump_json())
        return raw

    def fix_pr_files(self, pair: EvalPair) -> list[str]:
        """Python files changed by the fix PR (cached after the first fetch)."""
        if pair.fix_pr is None:
            raise ValueError(f"{pair.id}: no fix_pr")
        owner_repo = pair.ticket.split("#", 1)[0]
        path = self.pr_files_path(owner_repo, pair.fix_pr)
        if not path.is_file():
            files = self._fetch_pr_files(owner_repo, pair.fix_pr)
            self._write(path, json.dumps(files, indent=1))
        data: list[str] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def _fetch_pr_files(self, owner_repo: str, number: int) -> list[str]:
        api = self._settings.tickets.github.api_url.rstrip("/")
        url = f"{api}/repos/{owner_repo}/pulls/{number}/files"
        client = self._client or httpx.Client(timeout=self._settings.tickets.github.timeout_seconds)
        files: list[str] = []
        for page in range(1, 4):  # a fix PR touching >300 files is not a useful pair
            response = client.get(url, params={"per_page": 100, "page": page})
            if response.status_code != 200:
                raise TicketSourceError(f"GitHub returned HTTP {response.status_code} for {url}")
            batch = response.json()
            files.extend(item["filename"] for item in batch)
            if len(batch) < 100:
                break
        return files

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text)
