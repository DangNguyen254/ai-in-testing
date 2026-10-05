from __future__ import annotations

from collections.abc import Iterator
from pathlib import PurePosixPath

import pytest

from ticket2test.adapters.repo.base import RepoSource
from ticket2test.adapters.tickets.base import RawTicket, TicketSource
from ticket2test.llm import LLMClient


@pytest.mark.parametrize("abc", [TicketSource, RepoSource, LLMClient])
def test_interfaces_are_abstract(abc: type) -> None:
    with pytest.raises(TypeError):
        abc()


def test_minimal_ticket_source_implementation() -> None:
    class InMemory(TicketSource):
        name = "memory"

        def fetch(self, ref: str) -> RawTicket:
            return RawTicket(source=self.name, ref=ref, payload={"title": "t"})

    ticket = InMemory().fetch("X-1")
    assert ticket.source == "memory"
    assert ticket.payload == {"title": "t"}


def test_minimal_repo_source_implementation() -> None:
    files = {PurePosixPath("pkg/a.py"): "x = 1\n", PurePosixPath("README.md"): "hi"}

    class InMemory(RepoSource):
        def list_files(self, suffixes: tuple[str, ...] = (".py",)) -> Iterator[PurePosixPath]:
            return (p for p in files if p.suffix in suffixes)

        def read_text(self, path: PurePosixPath) -> str:
            return files[path]

    repo = InMemory()
    assert list(repo.list_files()) == [PurePosixPath("pkg/a.py")]
    assert repo.read_text(PurePosixPath("pkg/a.py")) == "x = 1\n"


def test_repo_source_has_no_write_methods() -> None:
    public = {n for n in dir(RepoSource) if not n.startswith("_")}
    assert public == {"list_files", "read_text"}
