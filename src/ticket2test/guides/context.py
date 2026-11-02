"""The ticket's area guide for the generation context.

A guide written by a person's Claude Code session (``<area>.authored.json`` in the guides
folder, see ``docs/guide-authoring-prompt.md``) wins over the one the ``guides`` step built: it
was written with tools, reading helpers down to their asserts and the data files. It holds only
the guide's fields; its names are checked against the index when it is loaded (unknown refs
removed), and a rebuild never overwrites it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ticket2test.config import Settings
from ticket2test.guides.check import check_guide
from ticket2test.guides.framework import FRAMEWORK
from ticket2test.guides.render import guide_context
from ticket2test.guides.run import guide_path, guides_dir, load_guide
from ticket2test.index.indexer import IndexData
from ticket2test.models.guide import AreaGuide, GuideOutput
from ticket2test.suitemap.build import sub_area

AUTHORED_SUFFIX = ".authored.json"
AUTHORED_MODEL = "claude-code (authored)"


def area_guide_text(
    area: str,
    repo_root: Path,
    index: IndexData,
    settings: Settings,
    files: list[str] | None = None,
) -> tuple[str, str]:
    """(text for the context, label). Empty when the area has no guide. ``files``: the test
    files the new test relates to; in a split area their sub-area guide is preferred. A guide
    whose source files changed since it was written is still used (the validators check every
    name in the output) but labelled stale, so the reviewer knows to rebuild it."""
    folder = guides_dir(repo_root, settings)
    names = [sub_area(area, f) for f in (files or [])] + [area]
    guide = next((g for n in names if (g := best_guide(folder, n, index)) is not None), None)
    framework = _framework_text(folder, index, settings) if settings.guides.framework else ""
    if guide is None:
        return (framework, FRAMEWORK) if framework else ("", "")
    area = guide.area
    changed = [
        path
        for path, sha in guide.sources.items()
        if (record := index.files.get(path)) is not None and record.sha256 != sha
    ]
    text = guide_context(
        guide, settings.guides.max_context_tokens, settings.context.chars_per_token
    )
    label = f"{area} (stale: {len(changed)} file(s) changed)" if changed else area
    if guide.model == AUTHORED_MODEL:
        label += " (written by Claude Code)"
    if framework:
        return f"{framework}\n\n{text}", f"{FRAMEWORK} + {label}"
    return text, label


def best_guide(folder: Path, area: str, index: IndexData) -> AreaGuide | None:
    """The authored guide when there is a valid one, else the built one."""
    return load_authored(folder, area, index) or load_guide(folder, area)


def authored_path(folder: Path, area: str) -> Path:
    built = guide_path(folder, area)
    return built.with_name(built.stem + AUTHORED_SUFFIX)


def load_authored(folder: Path, area: str, index: IndexData) -> AreaGuide | None:
    """``<area>.authored.json``, checked against the index; None when absent or invalid."""
    path = authored_path(folder, area)
    try:
        output = GuideOutput.model_validate_json(path.read_text(encoding="utf-8"))
        written = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except (OSError, ValidationError):
        return None
    checked, removed, unverified = check_guide(output, None, index)
    return AreaGuide(
        area=area,
        digest="",
        sources={},
        model=AUTHORED_MODEL,
        prompt_version="authored",
        built_at=written,
        input_pieces=[],
        input_tokens_estimate=0,
        guide=checked,
        raw=output,
        removed=removed,
        unverified=unverified,
    )


def _framework_text(folder: Path, index: IndexData, settings: Settings) -> str:
    """The framework guide for the context (``guides.framework_context_tokens``), if built."""
    guide = best_guide(folder, FRAMEWORK, index)
    if guide is None:
        return ""
    return guide_context(
        guide, settings.guides.framework_context_tokens, settings.context.chars_per_token
    )
