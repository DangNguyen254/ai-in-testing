"""Private terms: redacted before the LLM, reported in output and in this repo (never shown)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.test_validate import GOOD_CODE, _messages, _validate
from tests.test_validate import setup as setup  # the fixture
from ticket2test.cli import app
from ticket2test.config import Settings
from ticket2test.llm.base import LLMRequest, Message
from ticket2test.llm.factory import with_masking, with_privacy
from ticket2test.llm.fake import FakeLLMClient
from ticket2test.llm.masking import masker_of
from ticket2test.security.private import MARK, PrivateTerms

TERMS = [r"zorblax\w*", r"intra\.example\.test"]  # invented


def test_terms_are_redacted_and_found_by_position() -> None:
    terms = PrivateTerms(TERMS)
    text, count = terms.redact("Zorblax Cloud talks to intra.example.test\nzorblaxian")
    assert count == 3 and "orblax" not in text.lower() and text.count(MARK) == 3
    assert [(h.term, h.line) for h in terms.find("a\nZORBLAX b intra.example.test")] == [
        (1, 2),
        (2, 2),
    ]
    assert not PrivateTerms([]) and not PrivateTerms(["  "])


def test_the_privacy_wrapper_redacts_every_request() -> None:
    settings = Settings.model_validate({"security": {"private_terms": TERMS}})
    fake = FakeLLMClient(["{}"])
    client = with_privacy(with_masking(fake, settings), settings)
    request = LLMRequest(
        messages=(
            Message(role="system", content="You help zorblax."),
            Message(role="user", content="Ticket from intra.example.test"),
        )
    )
    client.complete(request)
    sent = "\n".join(m.content for m in fake.requests[0].messages)
    assert "zorblax" not in sent.lower() and "intra.example" not in sent and MARK in sent
    assert masker_of(client) is not None  # masking still found under the privacy wrapper
    assert with_privacy(fake, Settings()) is fake  # no terms: no wrapper


def test_private_terms_in_generated_output_are_errors(setup: Any) -> None:
    base = setup[0]
    settings = base.model_copy(deep=True)
    settings.security.private_terms = TERMS
    code = GOOD_CODE.replace('"""\n      1. Filter', '"""\n      0. Zorblax.\n      1. Filter', 1)
    messages = _messages(_validate(setup, code=code, settings=settings), "private")
    assert messages == ["private term #1 is in the code (line 20)"]  # the position, not the text
    marked = GOOD_CODE.replace("1. Filter", f"1. {MARK} Filter", 1)
    messages = _messages(_validate(setup, code=marked, settings=settings), "private")
    assert messages and "redacted name" in messages[0]


def _git_repo(folder: Path, files: dict[str, str]) -> Path:
    folder.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    (folder / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    return folder


def test_privacy_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _git_repo(
        tmp_path / "repo",
        {"clean.md": "nothing here\n", "leak.py": "x = 1\nhost = 'intra.example.test'\n",
         "ignored.txt": "zorblax\n"},
    )  # fmt: skip
    none = CliRunner().invoke(app, ["privacy-scan", str(repo)])
    assert none.exit_code == 0 and "nothing checked" in none.output
    monkeypatch.setenv("T2T_SECURITY__PRIVATE_TERMS", '["zorblax", "intra\\\\.example\\\\.test"]')
    result = CliRunner().invoke(app, ["privacy-scan", str(repo)])
    assert result.exit_code == 1, result.output
    assert "leak.py:2: private term #2" in result.output
    assert "ignored.txt" not in result.output  # git wouldn't commit it
    assert "intra.example" not in result.output and "zorblax" not in result.output
