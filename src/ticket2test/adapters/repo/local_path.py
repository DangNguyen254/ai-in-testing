"""Read-only RepoSource over a local directory."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath

from ticket2test.adapters.repo.base import RepoSource

_BINARY_SNIFF_BYTES = 8192


class RepoReadError(OSError):
    """A file can't be read as text (binary, too large, or not UTF-8)."""


class LocalPathRepoSource(RepoSource):
    """Lists and reads files under ``root``. There are no write methods.

    ``ignore`` patterns are matched (fnmatch) against every path segment, so ``build`` skips
    any directory named build and ``*_pb2.py`` skips generated files by name.
    """

    def __init__(
        self, root: Path, ignore: Sequence[str] = (), max_file_bytes: int = 1_000_000
    ) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")
        self._ignore = tuple(ignore)
        self._max_bytes = max_file_bytes

    def is_ignored(self, rel: PurePosixPath) -> bool:
        return any(fnmatch.fnmatch(part, pattern) for part in rel.parts for pattern in self._ignore)

    def list_files(self, suffixes: tuple[str, ...] = (".py",)) -> Iterator[PurePosixPath]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = PurePosixPath(Path(dirpath).relative_to(self.root).as_posix())
            # Prune ignored directories in place so os.walk never descends into them.
            dirnames[:] = sorted(
                d for d in dirnames if not self.is_ignored(rel_dir / d) and not d.startswith(".")
            )
            for name in sorted(filenames):
                rel = rel_dir / name if rel_dir != PurePosixPath(".") else PurePosixPath(name)
                if rel.suffix in suffixes and not self.is_ignored(rel):
                    yield rel

    def exists(self, path: PurePosixPath) -> bool:
        return self._abs(path).is_file()

    def read_bytes(self, path: PurePosixPath) -> bytes:
        full = self._abs(path)
        size = full.stat().st_size
        if size > self._max_bytes:
            raise RepoReadError(f"{path}: {size} bytes exceeds the {self._max_bytes}-byte limit")
        data = full.read_bytes()
        if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
            raise RepoReadError(f"{path}: looks like a binary file")
        return data

    def read_text(self, path: PurePosixPath) -> str:
        try:
            return self.read_bytes(path).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepoReadError(f"{path}: not valid UTF-8") from exc

    def _abs(self, path: PurePosixPath) -> Path:
        full = (self.root / Path(*path.parts)).resolve()
        if full != self.root and self.root not in full.parents:
            raise RepoReadError(f"{path}: outside the repo root")
        return full
