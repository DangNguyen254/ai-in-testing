"""Mine ticket <-> test pairs from git history: commits that remove a ticket-id skip.

A fix commit typically re-enables the test that was skipped while the bug was open. Two forms:
- a code skip: a skip decorator on the test whose arguments cite the ticket id
  (``@pytest.mark.skip(reason="ABC-123: ...")``), present before the commit and gone after;
- a data skip: a JSON data entry whose ``skip`` value cites the ticket id, removed by the commit.

The test must still exist after the commit (re-enabled, not deleted).

Without history (a checkout with no version-control metadata), ``mine_current_skips`` reads
the same two forms in the current tree: tests still skipped for an open ticket. Their pairs say
where a test for that ticket lives, without a fix commit to confirm it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from ticket2test.adapters.repo.git_history import Commit, GitHistoryReader
from ticket2test.config import Settings
from ticket2test.generate.entries import function_of
from ticket2test.index.extract import ParseError, extract_file

SkipKind = Literal["code_skip", "data_skip"]
CURRENT_TREE = "current tree"  # MinedPair.subject for pairs found without history


@dataclass(frozen=True)
class MinedPair:
    ticket: str
    test: str  # "path::Class::function" (pytest style, function level)
    commit: str
    subject: str
    kind: SkipKind


def mine_skip_removals(reader: GitHistoryReader, settings: Settings) -> list[MinedPair]:
    pattern = re.compile(settings.eval.ticket_id_pattern)
    found: dict[tuple[str, str], MinedPair] = {}
    for commit in reader.commits(settings.eval.max_commits):
        if not commit.parents:
            continue
        parent = commit.parents[0]
        for path in reader.changed_files(commit.sha):
            removed = _removed_skips(reader, parent, commit, path, pattern, settings)
            for ticket, test, kind in removed:
                found.setdefault(
                    (ticket, test), MinedPair(ticket, test, commit.sha, commit.subject, kind)
                )
    return sorted(found.values(), key=lambda p: (p.ticket, p.test))


def mine_current_skips(repo: Path, test_files: list[str], settings: Settings) -> list[MinedPair]:
    """(ticket, test) pairs from skips in the current tree that cite a ticket id: skip
    decorators on tests or their classes, and ``skip`` values in data entries (the module's
    data file, or a test's own file named after it)."""
    pattern = re.compile(settings.eval.ticket_id_pattern)
    suffix = settings.index.data_file_suffix
    found: dict[tuple[str, str], MinedPair] = {}

    def add(ticket: str, test: str, kind: SkipKind) -> None:
        found.setdefault((ticket, test), MinedPair(ticket, test, "", CURRENT_TREE, kind))

    for path in sorted(test_files):
        text = _read(repo / path)
        for ticket, test in sorted(_code_skips(text, path, pattern, settings)):
            add(ticket, test, "code_skip")
        tests = _test_functions(text, path, settings)
        folder = PurePosixPath(path).parent
        data_files = [str(PurePosixPath(path).with_suffix(suffix))]
        data_files += [str(folder / f"{t.rsplit('::', 1)[-1]}{suffix}") for t in tests]
        for data_path in dict.fromkeys(data_files):
            for ticket, entry_id in sorted(_data_skips(_read(repo / data_path), pattern, settings)):
                function = function_of(entry_id) or PurePosixPath(data_path).stem
                owner = next((t for t in tests if t.rsplit("::", 1)[-1] == function), None)
                if owner is not None:
                    add(ticket, owner, "data_skip")
    return sorted(found.values(), key=lambda p: (p.ticket, p.test))


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _removed_skips(
    reader: GitHistoryReader,
    parent: str,
    commit: Commit,
    path: str,
    pattern: re.Pattern[str],
    settings: Settings,
) -> list[tuple[str, str, SkipKind]]:
    suffix = settings.index.data_file_suffix
    if path.endswith(".py"):
        before = _code_skips(reader.file_at(parent, path), path, pattern, settings)
        after_text = reader.file_at(commit.sha, path)
        after = _code_skips(after_text, path, pattern, settings)
        alive = set(_test_functions(after_text, path, settings))
        return [
            (ticket, test, "code_skip")
            for (ticket, test) in sorted(before - after)
            if test in alive
        ]
    if path.endswith(suffix):
        test_file = str(PurePosixPath(path).with_suffix(".py"))
        source = reader.file_at(commit.sha, test_file)
        tests = _test_functions(source, test_file, settings)
        before_entries = _data_skips(reader.file_at(parent, path), pattern, settings)
        after_entries = _data_skips(reader.file_at(commit.sha, path), pattern, settings)
        removed = []
        for ticket, entry_id in sorted(before_entries - after_entries):
            function = function_of(entry_id)
            test = next((t for t in tests if t.rsplit("::", 1)[-1] == function), None)
            if test is not None:
                removed.append((ticket, test, "data_skip"))
        return removed  # type: ignore[return-value]
    return []


def _code_skips(
    text: str | None, path: str, pattern: re.Pattern[str], settings: Settings
) -> set[tuple[str, str]]:
    """(ticket, test) for every test whose own or class decorators skip citing a ticket."""
    if text is None:
        return set()
    try:
        info = extract_file(path, text.encode("utf-8"))
    except ParseError:
        return set()
    prefix = settings.index.test_function_prefix
    found: set[tuple[str, str]] = set()
    for fn in info.functions:
        if fn.name.startswith(prefix):
            for ticket in _skip_tickets(fn.decorators, pattern):
                found.add((ticket, f"{path}::{fn.name}"))
    for cls in info.classes:
        class_tickets = _skip_tickets(cls.decorators, pattern)
        for method in cls.methods:
            if method.name.startswith(prefix):
                for ticket in class_tickets | _skip_tickets(method.decorators, pattern):
                    found.add((ticket, f"{path}::{cls.name}::{method.name}"))
    return found


def _skip_tickets(decorators: list[str], pattern: re.Pattern[str]) -> set[str]:
    return {t for d in decorators if "skip" in d.lower() for t in pattern.findall(d)}


def _test_functions(text: str | None, path: str, settings: Settings) -> list[str]:
    if text is None:
        return []
    try:
        info = extract_file(path, text.encode("utf-8"))
    except ParseError:
        return []
    prefix, class_prefix = settings.index.test_function_prefix, settings.index.test_class_prefix
    tests = [f"{path}::{f.name}" for f in info.functions if f.name.startswith(prefix)]
    for cls in info.classes:
        if cls.name.startswith(class_prefix):
            tests += [
                f"{path}::{cls.name}::{m.name}" for m in cls.methods if m.name.startswith(prefix)
            ]
    return tests


def _data_skips(
    text: str | None, pattern: re.Pattern[str], settings: Settings
) -> set[tuple[str, str]]:
    """(ticket, entry id) for every entry whose ``skip`` value cites a ticket."""
    if text is None:
        return set()
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        return set()
    id_field = settings.data.id_field
    if isinstance(data, list):
        entries = [(str(e.get(id_field, "")), e) for e in data if isinstance(e, dict)]
    elif isinstance(data, dict):
        entries = [(str(k), v) for k, v in data.items() if isinstance(v, dict)]
    else:
        return set()
    found: set[tuple[str, str]] = set()
    for entry_id, entry in entries:
        if "skip" in entry:
            for ticket in pattern.findall(json.dumps(entry["skip"])):
                found.add((ticket, entry_id))
    return found
