"""Ticket -> TestCaseDraft(s)."""

from ticket2test.draft.generator import generate_drafts
from ticket2test.draft.render import render_markdown

__all__ = ["generate_drafts", "render_markdown"]
