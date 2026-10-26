"""Agent 2: a proposed member is inserted, checked by code, repaired at most a few times, and
kept as a patch. Nothing existing may change."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.llm.fake import FakeLLMClient
from ticket2test.models.gaps import GapVerdict, MissingPiece
from ticket2test.proposals import propose_gaps, use_kind
from ticket2test.proposals.check import check_patched, insert_member
from ticket2test.sandbox.runner import SandboxError, SuiteCollect

STANDIN = REPO_ROOT / "standin"
PAGE = "framework/pages/exceptions.py"

CLEAR = "def clear_expiry(self):\n    self.click(self.CLEAR_EXPIRY)\n"


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> IndexData:
    folder = tmp_path_factory.mktemp("idx")
    settings = Settings.model_validate({"paths": {"cache_dir": str(folder / "cache")}})
    built, _, _ = update_index(STANDIN, settings)
    return built


def _settings(tmp_path: Path, **proposals: Any) -> Settings:
    return Settings.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "proposals": {"enabled": True, "collect": False, **proposals},
        }
    )


def _owner(index: IndexData) -> str:
    return next(q for q in index.catalog.classes if q.endswith(".ExceptionEditorPage"))


def _gap(index: IndexData, name: str = "clear_expiry", status: str = "missing") -> GapVerdict:
    piece = MissingPiece(
        kind="page_object_member",
        owner="nav.exceptions.editor",
        name=name,
        needed_for=f"editor.{name}()",
        source="generated",
    )
    return GapVerdict(
        piece=piece,
        status=status,  # type: ignore[arg-type]
        owner_class=_owner(index),
        close=["CLEAR_EXPIRY"],
    )


def _reply(code: str, member: str = "clear_expiry", kind: str = "method") -> str:
    return json.dumps({"member": member, "kind": kind, "code": code, "rationale": "uses click"})


def _source() -> str:
    return (STANDIN / PAGE).read_text(encoding="utf-8")


def _check(index: IndexData, after: str, member: str = "clear_expiry", kind: str = "method"):
    return check_patched(
        _source(), after, "ExceptionEditorPage", member, kind, index.catalog, _owner(index)
    )


def test_a_valid_member_becomes_a_patch(index: IndexData, tmp_path: Path) -> None:
    fake = FakeLLMClient([_reply(CLEAR)])
    test_code = "def test_x(self):\n    self.editor.clear_expiry()\n"
    (proposal,) = propose_gaps([_gap(index)], test_code, index, _settings(tmp_path), fake, STANDIN)
    assert proposal.ok, proposal.findings
    assert proposal.kind == "method" and proposal.attempts == 1
    added = [line for line in proposal.diff.splitlines() if line.startswith("+ ")]
    assert any("def clear_expiry(self):" in line for line in added)
    assert not [line for line in proposal.diff.splitlines() if line.startswith("-   ")]
    assert proposal.prompt_version == "proposal_v1"
    user = fake.requests[0].messages[1].content
    assert "CLEAR_EXPIRY" in user and "click (method, from BasePage)" in user
    assert _source() == (STANDIN / PAGE).read_text(encoding="utf-8")  # repo untouched


def test_insert_keeps_the_class_indent() -> None:
    source = "class A:\n   X = 1\n\n   def a(self):\n      return 1\n\n\nB = 2\n"
    after = insert_member(source, "A", "def b(self):\n    return self.X\n")
    assert "\n   def b(self):\n       return self.X\n" in after
    assert after.endswith("\n\nB = 2\n")


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        # existing code changed
        (lambda s: s.replace("self.click(self.SAVE)", "self.click(self.NAME)"), "existing members"),
        (lambda s: s.replace("from urllib.parse import quote", "import os\nfrom urllib.parse "
                             "import quote"), "outside the class"),
        (lambda s: s.replace("class ExceptionListPage", "class ExceptionListPage2"),
         "outside ExceptionEditorPage"),
    ],
)  # fmt: skip
def test_changes_to_existing_code_are_rejected(
    index: IndexData, change: Any, expected: str
) -> None:
    after = insert_member(change(_source()), "ExceptionEditorPage", CLEAR)
    findings = _check(index, after)
    assert any(expected in f for f in findings), findings


@pytest.mark.parametrize(
    ("code", "member", "kind", "expected"),
    [
        (CLEAR.replace("clear_expiry", "reset_expiry"), "clear_expiry", "method", "must be named"),
        (CLEAR, "clear_expiry", "property", "make it a property"),
        ("@property\ndef clear_expiry(self):\n    return 1\n", "clear_expiry", "method",
         "make it a method"),
        ("def clear_expiry(self):\n    self.click(self.CLEAR_BUTTON)\n", "clear_expiry",
         "method", "self.CLEAR_BUTTON"),
        ("def clear_expiry(self):\n    wait_for(self.CLEAR_EXPIRY)\n", "clear_expiry", "method",
         "wait_for"),
        ("def save(self):\n    self.click(self.SAVE)\n", "save", "method", "already has"),
        ("def clear_expiry(self):\n    pass\n\ndef other(self):\n    pass\n", "clear_expiry",
         "method", "second definition"),
    ],
)  # fmt: skip
def test_member_checks(index: IndexData, code: str, member: str, kind: str, expected: str) -> None:
    after = insert_member(_source(), "ExceptionEditorPage", code)
    findings = _check(index, after, member, kind)
    assert any(expected in f for f in findings), findings


def test_a_property_with_a_setter_passes(index: IndexData) -> None:
    code = (
        "@property\ndef note(self):\n    return self.value_of(self.NAME)\n\n"
        "@note.setter\ndef note(self, value):\n    self.type(self.NAME, value)\n"
    )
    after = insert_member(_source(), "ExceptionEditorPage", code)
    assert _check(index, after, "note", "property") == []


def test_findings_go_back_and_the_loop_is_capped(index: IndexData, tmp_path: Path) -> None:
    bad = _reply("def clear_expiry(self):\n    self.click(self.CLEAR_BUTTON)\n")
    fake = FakeLLMClient([bad] * 10)
    settings = _settings(tmp_path, max_repairs=2)
    (proposal,) = propose_gaps([_gap(index)], "", index, settings, fake, STANDIN)
    assert not proposal.ok and proposal.diff == ""
    assert len(fake.requests) == 3  # the first try and two repairs
    assert "self.CLEAR_BUTTON" in fake.requests[1].messages[-1].content
    assert proposal.attempts == 3


def test_a_repair_that_fixes_it_passes(index: IndexData, tmp_path: Path) -> None:
    bad = _reply("def clear_expiry(self):\n    self.click(self.CLEAR_BUTTON)\n")
    fake = FakeLLMClient([bad, _reply(CLEAR)])
    (proposal,) = propose_gaps([_gap(index)], "", index, _settings(tmp_path), fake, STANDIN)
    assert proposal.ok and proposal.attempts == 2


def test_only_class_owned_gaps_and_the_cap(index: IndexData, tmp_path: Path) -> None:
    gaps = [
        _gap(index, "a_one"),
        _gap(index, "a_one"),  # duplicate
        _gap(index, "a_two", status="close_match"),
        _gap(index, "a_three"),  # over max_per_ticket
        _gap(index, "exists_already", status="exists"),
        GapVerdict(piece=_gap(index, "helper_x").piece, status="missing", owner_class=None),
    ]
    replies = [_reply(f"def {n}(self):\n    self.save()\n", n) for n in ("a_one", "a_two")]
    proposals = propose_gaps(
        gaps, "", index, _settings(tmp_path, max_per_ticket=2), FakeLLMClient(replies), STANDIN
    )
    assert [(p.member, p.ok) for p in proposals] == [("a_one", True), ("a_two", True)]


def test_use_kind() -> None:
    code = "def t(self):\n    p.clear_expiry()\n    p.note = 'x'\n    x = p.count\n"
    assert use_kind(code, "clear_expiry") == "method"
    assert use_kind(code, "note") == "property"
    assert use_kind(code, "count") == "property"
    assert use_kind(code, "absent") is None


def test_sandbox_collect(index: IndexData, tmp_path: Path, monkeypatch: Any) -> None:
    seen: dict[str, str] = {}

    def broken(repo: Path, settings: Settings, overlay: dict[str, str]) -> SuiteCollect:
        seen.update(overlay)
        return SuiteCollect(exit_code=2, timed_out=False, duration_seconds=1.0,
                            output_tail="ImportError: boom")  # fmt: skip

    monkeypatch.setattr("ticket2test.proposals.propose.collect_suite", broken)
    settings = _settings(tmp_path, collect=True, max_repairs=0)
    (proposal,) = propose_gaps(
        [_gap(index)], "", index, settings, FakeLLMClient([_reply(CLEAR)]), STANDIN
    )
    assert not proposal.ok and proposal.collect_ok is False
    assert "ImportError: boom" in proposal.findings[0]
    assert "def clear_expiry" in seen[PAGE]

    def missing(repo: Path, settings: Settings, overlay: dict[str, str]) -> SuiteCollect:
        raise SandboxError("Sandbox image not found")

    monkeypatch.setattr("ticket2test.proposals.propose.collect_suite", missing)
    (proposal,) = propose_gaps(
        [_gap(index)], "", index, settings, FakeLLMClient([_reply(CLEAR)]), STANDIN
    )
    assert proposal.ok and proposal.collect_ok is None
