"""Repository source interface. Read-only by design: there are no write methods."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import PurePosixPath


class RepoSource(ABC):
    """Read-only view of a target codebase."""

    @abstractmethod
    def list_files(self, suffixes: tuple[str, ...] = (".py",)) -> Iterator[PurePosixPath]:
        """Yield repo-relative paths of files with the given suffixes."""

    @abstractmethod
    def read_text(self, path: PurePosixPath) -> str:
        """Return the text of one repo-relative file."""
