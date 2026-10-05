"""Configuration: defaults < config.yaml < environment variables.

Environment variables use the ``T2T_`` prefix and ``__`` as the nesting delimiter,
e.g. ``T2T_RETRIEVAL__TOP_K=5`` overrides ``retrieval.top_k``.

Secrets (API keys, tokens) are never part of this config. Adapters and LLM clients
read them directly from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_PATH = Path("config.yaml")
CONFIG_PATH_ENV_VAR = "T2T_CONFIG"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMSettings(_Section):
    provider: str = "fake"
    model: str = ""
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int | None = 0
    max_retries_on_bad_json: int = Field(default=2, ge=0)


class RetrievalSettings(_Section):
    top_k: int = Field(default=10, ge=1)
    max_followup_rounds: int = Field(default=2, ge=0)


class ContextSettings(_Section):
    max_tokens: int = Field(default=12000, ge=1)


class RepairSettings(_Section):
    max_attempts: int = Field(default=3, ge=0)


class SandboxSettings(_Section):
    runtime: Literal["docker", "podman"] = "docker"
    timeout_seconds: int = Field(default=120, ge=1)


class GitHubSettings(_Section):
    api_url: str = "https://api.github.com"
    timeout_seconds: float = Field(default=30.0, gt=0)
    comments_per_page: int = Field(default=100, ge=1, le=100)
    max_comment_pages: int = Field(default=10, ge=1)
    # Labels starting with one of these prefixes become Ticket.components (prefix stripped).
    component_label_prefixes: list[str] = Field(default_factory=list)


class JiraSettings(_Section):
    # Optional "https://<host>/browse" base used to turn issue keys into URLs.
    browse_url: str | None = None
    # Map Ticket fields to custom Jira field IDs, e.g. {"steps_to_reproduce": "customfield_10050"}.
    field_map: dict[Literal["steps_to_reproduce", "expected", "actual"], str] = Field(
        default_factory=dict
    )


class TicketSettings(_Section):
    github: GitHubSettings = GitHubSettings()
    jira: JiraSettings = JiraSettings()


class NormalizeSettings(_Section):
    # Long threads keep the first and the most recent comments, up to this many in total.
    max_comments: int = Field(default=50, ge=0)
    max_comment_chars: int = Field(default=4000, ge=100)


class PathSettings(_Section):
    output_dir: Path = Path("output")
    cache_dir: Path = Path(".t2t_cache")
    debug_log_dir: Path = Path("debug_logs")


class Settings(BaseSettings):
    """Effective pipeline configuration."""

    model_config = SettingsConfigDict(
        env_prefix="T2T_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    llm: LLMSettings = LLMSettings()
    tickets: TicketSettings = TicketSettings()
    normalize: NormalizeSettings = NormalizeSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    context: ContextSettings = ContextSettings()
    repair: RepairSettings = RepairSettings()
    sandbox: SandboxSettings = SandboxSettings()
    paths: PathSettings = PathSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Earlier sources win. YAML sits below env vars so env always overrides the file.
        return (init_settings, env_settings, YamlConfigSettingsSource(settings_cls))


def resolve_config_path(config_path: Path | None = None) -> tuple[Path, bool]:
    """Return the config path to use and whether it was explicitly requested."""
    if config_path is not None:
        return config_path, True
    env_path = os.environ.get(CONFIG_PATH_ENV_VAR)
    if env_path:
        return Path(env_path), True
    return DEFAULT_CONFIG_PATH, False


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML (if present) with environment-variable overrides.

    An explicitly requested config file (argument or ``T2T_CONFIG``) must exist.
    The default ``config.yaml`` is optional; built-in defaults apply without it.
    """
    path, explicit = resolve_config_path(config_path)
    if not path.is_file():
        if explicit:
            raise FileNotFoundError(f"Config file not found: {path}")
        return Settings()

    class _FileBackedSettings(Settings):
        model_config = SettingsConfigDict(yaml_file=path, yaml_file_encoding="utf-8")

    # Sources are already merged; re-wrap as a plain Settings so callers get one type.
    return Settings.model_validate(_FileBackedSettings().model_dump())
