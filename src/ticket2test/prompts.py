"""Versioned prompt templates loaded from ``prompts/<version>.md``.

File format: a ``# System`` section and a ``# User`` section (lines exactly as written).
Placeholders are ``{{name}}``; every placeholder must be filled and no value may go unused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_SECTIONS = ("# System", "# User")


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    system: str
    user: str

    def render_user(self, **values: str) -> str:
        wanted = set(_PLACEHOLDER.findall(self.user))
        missing = wanted - values.keys()
        extra = values.keys() - wanted
        if missing or extra:
            raise PromptError(
                f"Prompt {self.version}: missing {sorted(missing)}, unused {sorted(extra)}"
            )
        return _PLACEHOLDER.sub(lambda m: values[m.group(1)], self.user)


def default_prompts_dir() -> Path:
    # src/ticket2test/prompts.py -> repo root / prompts
    return Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(version: str, prompts_dir: Path | None = None) -> PromptTemplate:
    if not re.fullmatch(r"[\w.-]+", version):
        raise PromptError(f"Invalid prompt version: {version!r}")
    path = (prompts_dir or default_prompts_dir()) / f"{version}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PromptError(f"Prompt file not found: {path}") from exc

    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.rstrip() in _SECTIONS:
            current = sections.setdefault(line.rstrip(), [])
        elif current is not None:
            current.append(line)
    if set(sections) != set(_SECTIONS):
        raise PromptError(f"{path} must contain '# System' and '# User' sections")
    return PromptTemplate(
        version=version,
        system="\n".join(sections["# System"]).strip(),
        user="\n".join(sections["# User"]).strip(),
    )
