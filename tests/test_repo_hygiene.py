"""Guards for the repo-level hard constraints (secrets, gitignore, SDK isolation)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yaml", ".yml", ".txt", ".json", ".cfg", ".ini", ""}

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "openai_style_key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "bearer_token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    "password_in_url": re.compile(r"://[^/\s:@]+:[^/\s@]{3,}@"),
}

PROVIDER_SDKS = (
    "openai",
    "anthropic",
    "google.generativeai",
    "google.genai",
    "mistralai",
    "cohere",
)


def _repo_files() -> list[Path]:
    out = []
    for path in REPO_ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.is_file() and path.name != ".env" and path.suffix in TEXT_SUFFIXES | {".example"}:
            out.append(path)
    return out


@pytest.mark.parametrize("name", sorted(SECRET_PATTERNS))
def test_no_secret_like_strings_in_repo(name: str) -> None:
    pattern = SECRET_PATTERNS[name]
    this_file = Path(__file__).resolve()
    hits = [
        str(p.relative_to(REPO_ROOT))
        for p in _repo_files()
        if p.resolve() != this_file
        and pattern.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert hits == []


def test_env_example_has_only_placeholders() -> None:
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        _, value = line.split("=", 1)
        assert value.startswith("your-") and value.endswith("-here"), line


def test_gitignore_covers_secrets_and_outputs() -> None:
    entries = set((REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    for required in (".env", ".venv/", "output/", ".t2t_cache/", "debug_logs/"):
        assert required in entries


def test_provider_sdks_imported_only_in_llm_package() -> None:
    import_re = re.compile(
        r"^\s*(?:import|from)\s+(" + "|".join(re.escape(m) for m in PROVIDER_SDKS) + r")\b",
        re.MULTILINE,
    )
    src = REPO_ROOT / "src" / "ticket2test"
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in src.rglob("*.py")
        if "llm" not in p.relative_to(src).parts[:1] and import_re.search(p.read_text("utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize(
    ("name", "sample"),
    [
        ("aws_access_key", "AKIA" + "ABCDEFGHIJKLMNOP"),
        ("github_token", "ghp_" + "a" * 36),
        ("openai_style_key", "sk-" + "x" * 24),
        ("slack_token", "xoxb-" + "1234567890ab"),
        ("private_key", "-----BEGIN RSA " + "PRIVATE KEY-----"),
        ("bearer_token", "Authorization: Bearer " + "t" * 24),
        ("password_in_url", "postgres://user:" + "hunter2@db/x"),
    ],
)
def test_secret_patterns_detect_fake_samples(name: str, sample: str) -> None:
    assert SECRET_PATTERNS[name].search(sample)
