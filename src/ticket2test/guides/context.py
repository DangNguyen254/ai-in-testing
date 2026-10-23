"""The ticket's area guide for the generation context."""

from __future__ import annotations

from pathlib import Path

from ticket2test.config import Settings
from ticket2test.guides.render import guide_context
from ticket2test.guides.run import guides_dir, load_guide
from ticket2test.index.indexer import IndexData


def area_guide_text(
    area: str, repo_root: Path, index: IndexData, settings: Settings
) -> tuple[str, str]:
    """(text for the context, label). Empty when the area has no guide. A guide whose source
    files changed since it was written is still used (the validators check every name in the
    output) but labelled stale, so the reviewer knows to rebuild it."""
    guide = load_guide(guides_dir(repo_root, settings), area)
    if guide is None:
        return "", ""
    changed = [
        path
        for path, sha in guide.sources.items()
        if (record := index.files.get(path)) is not None and record.sha256 != sha
    ]
    text = guide_context(
        guide, settings.guides.max_context_tokens, settings.context.chars_per_token
    )
    return text, f"{area} (stale: {len(changed)} file(s) changed)" if changed else area
