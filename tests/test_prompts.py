from __future__ import annotations

from pathlib import Path

import pytest

from ticket2test.prompts import PromptError, load_prompt


def test_draft_v1_loads_and_renders() -> None:
    prompt = load_prompt("draft_v1")
    assert prompt.version == "draft_v1"
    assert "insufficient_info" in prompt.system
    text = prompt.render_user(ticket_json='{"id": "X"}', priorities="P0, P1", suites="smoke")
    assert '{"id": "X"}' in text and "P0, P1" in text
    assert "{{" not in text


def test_missing_or_extra_placeholders_are_errors() -> None:
    prompt = load_prompt("draft_v1")
    with pytest.raises(PromptError, match="missing"):
        prompt.render_user(ticket_json="x")
    with pytest.raises(PromptError, match="unused"):
        prompt.render_user(ticket_json="x", priorities="p", suites="s", extra="e")


def test_invalid_version_and_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="Invalid"):
        load_prompt("../secrets")
    with pytest.raises(PromptError, match="not found"):
        load_prompt("draft_v1", tmp_path)


def test_sections_are_required(tmp_path: Path) -> None:
    (tmp_path / "broken.md").write_text("# System\nonly system\n", encoding="utf-8")
    with pytest.raises(PromptError, match="sections"):
        load_prompt("broken", tmp_path)
