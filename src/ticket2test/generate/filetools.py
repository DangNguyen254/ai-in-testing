"""The planner's tools: the repo copy read as text. Read-only, nothing executed.

Three tools: ``read`` (a file, or a line range of it), ``grep`` (a pattern across the copy)
and ``list`` (one folder). Every path is resolved inside the root and refused outside it;
ignored folders (``index.ignore``) and files over ``index.max_file_bytes`` are not read; every
output is scrubbed and cut at the planner's cap.
"""

from __future__ import annotations

import fnmatch
import re
from collections import Counter
from pathlib import Path

from ticket2test.config import PlannerSettings, Settings
from ticket2test.models.plan import PlanAction
from ticket2test.security import scrub_text

_TEXT = {".py", ".json", ".md", ".txt", ".yaml", ".yml", ".ini", ".cfg", ".toml"}
_RANGE = re.compile(r"^(?P<path>.*?):(?P<first>\d+)(?:-(?P<last>\d+))?$")


class FileTools:
    def __init__(self, root: Path, settings: Settings) -> None:
        self.root = root.resolve()
        self.cfg: PlannerSettings = settings.generate.planner
        self.ignore = settings.index.ignore
        self.max_bytes = settings.index.max_file_bytes
        self._files: list[Path] | None = None

    def run(self, action: PlanAction) -> str:
        handler = {"read": self._read, "grep": self._grep, "list": self._list}[action.tool]
        text = scrub_text(handler(action.arg.strip()))
        limit = self.cfg.max_output_chars
        if len(text) > limit:
            text = text[:limit] + f"\n... (cut at {limit} characters)"
        return text

    # --- paths ---------------------------------------------------------------------------

    def _inside(self, written: str) -> Path | None:
        """The path inside the root, or None when it leaves it or is ignored."""
        rel = written.strip().strip("`'\"").lstrip("/")
        if rel.startswith("./"):
            rel = rel[2:]
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            return None
        if self._ignored(path):
            return None
        return path

    def _ignored(self, path: Path) -> bool:
        parts = path.relative_to(self.root).parts
        return any(fnmatch.fnmatchcase(part, pat) for part in parts for pat in self.ignore)

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _all(self) -> list[Path]:
        if self._files is None:
            self._files = sorted(
                p
                for p in self.root.rglob("*")
                if p.suffix in _TEXT
                and p.is_file()
                and not p.is_symlink()
                and not self._ignored(p)
                and p.stat().st_size <= self.max_bytes
            )
        return self._files

    # --- tools ---------------------------------------------------------------------------

    def _read(self, arg: str) -> str:
        first, last = 1, 0
        ranged = _RANGE.match(arg)
        if ranged and self._inside(ranged["path"]) is not None:
            arg, first = ranged["path"], max(int(ranged["first"]), 1)
            last = int(ranged["last"] or 0)
        path = self._inside(arg)
        if path is None or not path.is_file():
            return f"no such file in the suite: {arg!r} (use list or grep to find it)"
        if path.stat().st_size > self.max_bytes:
            return f"{self._rel(path)}: too large to read"
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        cap = self.cfg.read_lines
        end = min(last or len(lines), first + cap - 1, len(lines))
        body = "\n".join(f"{n}: {lines[n - 1]}" for n in range(first, end + 1))
        head = f"{self._rel(path)}, lines {first}-{end} of {len(lines)}"
        if end < len(lines):
            head += f" (more: read {self._rel(path)}:{end + 1}-{min(end + cap, len(lines))})"
        return f"{head}\n{body}"

    def _grep(self, arg: str) -> str:
        pattern, _, folder = arg.partition(" @ ")
        base = self._inside(folder) if folder.strip() else self.root
        if base is None or not base.exists():
            return f"no such folder in the suite: {folder.strip()!r}"
        try:
            regex = re.compile(pattern)
        except re.error:
            regex = re.compile(re.escape(pattern))
        hits: list[str] = []
        more: Counter[str] = Counter()
        for path in self._all():
            if base != self.root and base not in path.parents and path != base:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    if len(hits) < self.cfg.grep_hits:
                        hits.append(f"{self._rel(path)}:{number}: {line.strip()[:200]}")
                    else:
                        more[self._rel(path).split("/")[0]] += 1
        if not hits:
            return f"no line matches {pattern!r}"
        if more:
            where = ", ".join(f"{name}/ {n}" for name, n in more.most_common(6))
            hits.append(f"... {sum(more.values())} more match(es), not shown: {where}")
        return "\n".join(hits)

    def _list(self, arg: str) -> str:
        path = self._inside(arg if arg not in (".", "/") else "")
        if path is None or not path.is_dir():
            return f"no such folder in the suite: {arg!r}"
        rows = []
        for child in sorted(path.iterdir()):
            if self._ignored(child) or child.is_symlink():
                continue
            if child.is_dir():
                rows.append(f"{self._rel(child)}/")
            elif child.suffix in _TEXT:
                rows.append(f"{self._rel(child)} ({child.stat().st_size // 1024 + 1} KiB)")
        return "\n".join(rows[:300]) or "(empty)"
