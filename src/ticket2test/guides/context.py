"""The ticket's area guide for the generation context."""

from __future__ import annotations

from pathlib import Path

from ticket2test.config import Settings
from ticket2test.guides.render import guide_context
from ticket2test.guides.run import guides_dir, load_guide
from ticket2test.index.indexer import IndexData
from ticket2test.suitemap.build import sub_area


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
    guide = next((g for n in names if (g := load_guide(folder, n)) is not None), None)
    if guide is None:
        return "", ""
    area = guide.area
    changed = [
        path
        for path, sha in guide.sources.items()
        if (record := index.files.get(path)) is not None and record.sha256 != sha
    ]
    text = guide_context(
        guide, settings.guides.max_context_tokens, settings.context.chars_per_token
    )
    return text, f"{area} (stale: {len(changed)} file(s) changed)" if changed else area
