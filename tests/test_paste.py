"""Pasted tickets: a Markdown file per ticket, filled in by hand when the tracker's API can't
be used. Invented example content only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ticket2test.adapters.tickets.base import TicketNotFoundError
from ticket2test.adapters.tickets.paste import TEMPLATE, PastedTicketSource
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.normalize import NormalizationError, normalize

FILLED = """\
# DEMO-7: Saving a rule with an empty name shows no error

## Components
rules, top bar

## Labels
- ui
- regression

## Description
The rule editor accepts an empty name.

## Steps to reproduce
1. Open the rules page.
2. Add a rule and leave the name empty.
3. Click save.

## Expected
An error says the name is required.

## Actual
The rule is saved without a name.

## Notes from triage
Seen on the staging build only.

## Attachments
plan.md
screen.png

## Comments
First look: reproducible.
---
Fixed in the next build.

## Links
https://tracker.example.com/browse/DEMO-6
https://git.example.com/group/app/-/merge_requests/12
"""


def _ticket(tmp_path: Path, text: str, files: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    folder = tmp_path / "tickets"
    folder.mkdir(exist_ok=True)
    (folder / "DEMO-7.md").write_text(text, encoding="utf-8")
    for name, body in (files or {}).items():
        (folder / name).write_text(body, encoding="utf-8")
    raw = PastedTicketSource(folder).fetch("DEMO-7")
    return normalize(raw, Settings())


def test_a_filled_in_file_becomes_a_ticket(tmp_path: Path) -> None:
    ticket = _ticket(tmp_path, FILLED, {"plan.md": "Case 3: the name field is required."})
    assert (ticket.id, ticket.title) == (
        "DEMO-7",
        "Saving a rule with an empty name shows no error",
    )
    assert ticket.source.system == "jira" and ticket.source.ref == "DEMO-7"
    assert ticket.components == ["rules", "top bar"] and ticket.labels == ["ui", "regression"]
    assert len(ticket.steps_to_reproduce) == 3 and "save" in ticket.steps_to_reproduce[2]
    assert ticket.expected == "An error says the name is required."
    assert ticket.actual == "The rule is saved without a name."
    assert [c.body for c in ticket.comments] == [
        "First look: reproducible.",
        "Fixed in the next build.",
    ]
    assert ticket.links == [
        "https://tracker.example.com/browse/DEMO-6",
        "https://git.example.com/group/app/-/merge_requests/12",
    ]
    description = ticket.description or ""
    assert "accepts an empty name" in description
    assert "Notes from triage:" in description  # an unknown section is kept, with its heading
    assert "Attachment plan.md:\nCase 3" in description  # a readable attachment is read
    assert "[attachment not read: screen.png]" in description


def test_steps_and_expected_may_come_from_the_pasted_test_plan(tmp_path: Path) -> None:
    text = (
        "# DEMO-7: Empty rule names are accepted\n\n## Description\nSee the test plan.\n\n"
        "## Test plan\nSteps to reproduce:\n1. Open the rules page.\n2. Save a rule with no "
        "name.\n\nExpected result:\nThe save is blocked with an error.\n"
    )
    ticket = _ticket(tmp_path, text)
    assert len(ticket.steps_to_reproduce) == 2
    assert ticket.expected and "blocked" in ticket.expected
    assert "Test plan (pasted):" in (ticket.description or "")


def test_the_empty_template_is_not_a_ticket_and_a_missing_file_is_reported(
    tmp_path: Path,
) -> None:
    with pytest.raises(NormalizationError, match="first line"):
        _ticket(tmp_path, TEMPLATE.format(key="DEMO-7"))
    with pytest.raises(TicketNotFoundError):
        PastedTicketSource(tmp_path).fetch("DEMO-8")


def test_new_ticket_then_normalize_from_the_command_line(tmp_path: Path) -> None:
    folder = tmp_path / "tickets"
    runner = CliRunner()
    made = runner.invoke(app, ["new-ticket", "DEMO-7", "--dir", str(folder)])
    assert made.exit_code == 0, made.output
    assert (folder / "DEMO-7.md").read_text("utf-8").startswith("# DEMO-7: <title>")
    again = runner.invoke(app, ["new-ticket", "DEMO-7", "--dir", str(folder)])
    assert again.exit_code == 1  # never overwrites a filled-in file

    (folder / "DEMO-7.md").write_text(FILLED, encoding="utf-8")
    out = tmp_path / "DEMO-7.json"
    done = runner.invoke(app, ["normalize", "DEMO-7", "--paste", str(folder), "--out", str(out)])
    assert done.exit_code == 0, done.output
    assert json.loads(out.read_text("utf-8"))["expected"] == "An error says the name is required."
