"""Read-only access to a repo's git history (for mining eval pairs).

Only read commands are ever run (``log``, ``diff-tree``, ``show``); the class has no method
that writes. Hard Constraint 4: the pipeline never modifies a target repo.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Runner = Callable[..., subprocess.CompletedProcess[str]]

_READ_COMMANDS = frozenset({"log", "diff-tree", "show"})
_SEP = "\x1f"


class GitHistoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    subject: str
    date: str  # ISO 8601, committer date


class GitHistoryReader:
    def __init__(self, repo: Path, runner: Runner = subprocess.run) -> None:
        self.repo = repo
        self._run = runner

    def commits(self, max_count: int) -> list[Commit]:
        """Newest first, at most ``max_count`` (an explicit cap, Hard Constraint 6)."""
        out = self._git("log", f"--max-count={max_count}", f"--format=%H{_SEP}%P{_SEP}%cI{_SEP}%s")
        commits = []
        for line in out.splitlines():
            if not line.strip():
                continue
            sha, parents, date, subject = line.split(_SEP, 3)
            commits.append(Commit(sha, tuple(parents.split()), subject, date))
        return commits

    def changed_files(self, sha: str) -> list[str]:
        out = self._git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha)
        return [line for line in out.splitlines() if line.strip()]

    def file_at(self, sha: str, path: str) -> str | None:
        """The file's content at a commit, or None if it doesn't exist there."""
        try:
            return self._git("show", f"{sha}:{path}")
        except GitHistoryError:
            return None

    def _git(self, command: str, *args: str) -> str:
        if command not in _READ_COMMANDS:  # pragma: no cover - guarded by the API above
            raise GitHistoryError(f"refusing a non-read git command: {command}")
        proc = self._run(
            ["git", "-C", str(self.repo), "--no-pager", command, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            raise GitHistoryError(f"git {command} failed: {proc.stderr.strip()[:300]}")
        return proc.stdout
