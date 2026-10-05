from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import FIXTURES, github_raw
from ticket2test import __version__
from ticket2test.adapters.tickets.base import RawTicket, TicketNotFoundError
from ticket2test.adapters.tickets.github import GitHubIssueSource
from ticket2test.cli import app
from ticket2test.models import Ticket

SUBCOMMANDS = ["normalize", "draft", "index", "search", "retrieve", "generate", "validate", "eval"]

runner = CliRunner()


def test_help_lists_all_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in SUBCOMMANDS:
        assert name in result.output
    assert "--debug-log" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


PLACEHOLDERS = [name for name in SUBCOMMANDS if name not in ("normalize", "draft")]


@pytest.mark.parametrize("name", PLACEHOLDERS)
def test_placeholder_subcommands_fail_clearly(name: str) -> None:
    result = runner.invoke(app, [name])
    assert result.exit_code == 1
    assert "Not implemented yet" in result.output


def test_missing_config_file_is_reported(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--config", str(tmp_path / "missing.yaml"), "index"])
    assert result.exit_code == 2
    assert "Config file not found" in result.output


def test_normalize_jira_export_writes_ticket(tmp_path: Path) -> None:
    out = tmp_path / "t.json"
    export = str(FIXTURES / "jira" / "adf_issue.json")
    result = runner.invoke(
        app, ["normalize", "DEMO-101", "--jira-export", export, "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    ticket = Ticket.model_validate_json(out.read_text(encoding="utf-8"))
    assert ticket.id == "DEMO-101"


def test_normalize_github_default_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_fetch(self: GitHubIssueSource, ref: str) -> RawTicket:
        return github_raw(1482)

    monkeypatch.setattr(GitHubIssueSource, "fetch", fake_fetch)
    raw_out = tmp_path / "raw.json"
    result = runner.invoke(app, ["normalize", "encode/httpx#1482", "--raw-out", str(raw_out)])
    assert result.exit_code == 0, result.output
    written = tmp_path / "output" / "tickets" / "encode_httpx_1482.json"  # cwd is tmp_path
    assert Ticket.model_validate_json(written.read_text(encoding="utf-8")).id == "encode/httpx#1482"
    assert RawTicket.model_validate_json(raw_out.read_text(encoding="utf-8")).source == "github"


def test_normalize_reports_source_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(self: GitHubIssueSource, ref: str) -> RawTicket:
        raise TicketNotFoundError("GitHub issue not found: encode/httpx#1")

    monkeypatch.setattr(GitHubIssueSource, "fetch", fake_fetch)
    result = runner.invoke(app, ["normalize", "encode/httpx#1"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_normalize_rejects_unknown_ref() -> None:
    result = runner.invoke(app, ["normalize", "DEMO-1"])
    assert result.exit_code == 2
    assert "--jira-export" in result.output
