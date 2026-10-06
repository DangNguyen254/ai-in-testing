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


# The pipeline's LLM steps; each provider may map some of them to another model.
LLMStep = Literal["draft", "query_rewrite", "retrieval_followup", "generate"]


class ClaudeCodeCLISettings(_Section):
    # "claude" on PATH, or a full path (set via env; never commit a machine-specific path).
    executable: str = "claude"
    model: str = "claude-sonnet-5-5"
    step_models: dict[LLMStep, str] = {}  # per-step override of `model`
    # Working directory for CLI calls (inside the repo, git-ignored).
    workdir: Path = Path(".scratch/claude-cli")


class ClaudeAPISettings(_Section):
    model: str = "claude-sonnet-5-5"
    step_models: dict[LLMStep, str] = {}  # per-step override of `model`
    # Server-side refusal fallback (`fallbacks: "default"`); Claude API only.
    fallbacks: bool = True
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None


class GeminiSettings(_Section):
    model: str = ""  # required when provider is "gemini"; config-only
    step_models: dict[LLMStep, str] = {}  # per-step override of `model`


class LLMSettings(_Section):
    provider: Literal["claude_code_cli", "claude", "gemini"] = "claude_code_cli"
    # Applied where the provider supports it (Gemini). The Claude CLI exposes no temperature,
    # and current Claude models reject non-default values, so Claude runs are not fully
    # deterministic.
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int | None = 0
    max_retries_on_bad_json: int = Field(default=2, ge=0)
    max_output_tokens: int = Field(default=16000, ge=1)
    timeout_seconds: float = Field(default=300.0, gt=0)
    claude_code_cli: ClaudeCodeCLISettings = ClaudeCodeCLISettings()
    claude: ClaudeAPISettings = ClaudeAPISettings()
    gemini: GeminiSettings = GeminiSettings()


class MarkerSettings(_Section):
    """Marker values of the target suite. Generic placeholders; set real ones per environment."""

    priorities: list[str] = Field(default_factory=lambda: ["p0", "p1", "p2", "p3"], min_length=1)
    suites: list[str] = Field(default_factory=lambda: ["smoke", "regression"], min_length=1)
    project: str = "example-project"
    required: list[str] = Field(
        default_factory=lambda: ["priority", "project", "component", "suite"]
    )


class EvalSettings(_Section):
    # Ticket ids in skip reasons (used to mine ticket <-> test pairs from git history).
    ticket_id_pattern: str = r"\b[A-Z][A-Z0-9]+-\d+\b"


class DraftSettings(_Section):
    prompt_version: str = "draft_v1"
    # Comments go into the prompt in order until this many characters; the rest are dropped.
    max_comment_chars: int = Field(default=20000, ge=0)
    # When the component can't be identified, confidence is capped at this value.
    unknown_component_max_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class IndexSettings(_Section):
    # fnmatch patterns matched against every path segment.
    ignore: list[str] = Field(
        default_factory=lambda: [
            ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__", "node_modules",
            ".tox", ".nox", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".scratch",
            "build", "dist", "site-packages", "*.egg-info", "vendor", "vendored",
            "third_party", "*_pb2.py", "*_pb2_grpc.py",
        ]
    )  # fmt: skip
    max_file_bytes: int = Field(default=1_000_000, ge=1)
    test_file_globs: list[str] = Field(default_factory=lambda: ["test_*.py", "*_test.py"])
    test_function_prefix: str = "test"
    test_class_prefix: str = "Test"
    data_file_suffix: str = ".json"  # test_x.py -> test_x.json
    chain_roots: list[str] = Field(default_factory=lambda: ["nav"])
    max_chain_depth: int = Field(default=4, ge=1)
    max_chain_entries: int = Field(default=5000, ge=1)
    name_boost: int = Field(default=3, ge=1)  # symbol name repeats in the search text
    save_attempts: int = Field(default=5, ge=1)  # index file rename retries (Windows locks)


class DataSettings(_Section):
    """Shape of the target suite's per-test JSON data files.

    ``array``: a top-level list of entries, each naming its pytest id in ``id_field``.
    ``object``: a top-level object keyed by pytest id. Reading accepts both; ``format`` is how
    new data is written when no template data file says otherwise.
    """

    format: Literal["array", "object"] = "array"
    id_field: str = "test_id"
    # How a test reads its entry: these expressions are indexed (``self.params["key"]``).
    access: list[str] = Field(default_factory=lambda: ["self.params", "params"])
    # Sections the framework applies before the test (always consumed).
    seed_sections: list[str] = Field(default_factory=lambda: ["settings", "policy", "tenants"])
    # Expectation section -> the validation helper that reads it. An entry has at most one,
    # and only when the test calls its helper.
    expectation_sections: dict[str, str] = Field(
        default_factory=lambda: {
            "targets": "self.verify_targets",
            "interactions": "self.verify_interactions",
        }
    )
    # Per-entry overrides that a new entry never inherits from its base entry.
    per_entry_keys: list[str] = Field(default_factory=lambda: ["priority", "skip"])


class PythonStyle(_Section):
    indent_width: int = Field(default=3, ge=1, le=8)
    line_length: int = Field(default=100, ge=40)
    line_ending: Literal["lf", "cr-lf"] = "lf"
    quote_style: Literal["double", "single"] = "double"
    strip_annotations: bool = True
    final_newline: bool = True
    # First-party import roots for import sorting; empty: the target repo's top-level packages.
    first_party: list[str] = Field(default_factory=list)


class JsonStyle(_Section):
    indent: int = Field(default=3, ge=0, le=8)
    key_separator: str = ":"
    item_separator: str = ","
    ensure_ascii: bool = False
    final_newline: bool = True


class StyleSettings(_Section):
    """The target suite's style rules, applied to generated code and data by a formatter."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    python: PythonStyle = PythonStyle()
    json_files: JsonStyle = Field(default_factory=JsonStyle, alias="json")


class RerankSettings(_Section):
    """Deterministic, feature-based reranking of the fused candidates (no LLM)."""

    enabled: bool = True
    max_chunks_per_file: int = Field(default=3, ge=1)  # diversity in the final top_k
    min_tests: int = Field(default=2, ge=0)  # tests kept in top_k when any were found
    identifier_weight: float = Field(default=0.3, ge=0.0)  # references verified identifiers
    definition_weight: float = Field(default=0.2, ge=0.0)  # defines a verified identifier
    test_link_weight: float = Field(default=0.15, ge=0.0)  # a test of a top source chunk
    path_weight: float = Field(default=0.15, ge=0.0)  # ticket words in the file path


class RetrievalSettings(_Section):
    top_k: int = Field(default=10, ge=1)
    max_followup_rounds: int = Field(default=2, ge=0)
    use_llm: bool = True  # query rewrite + follow-up rounds; False = deterministic only
    query_rewrite_prompt: str = "query_rewrite_v1"
    followup_prompt: str = "retrieval_followup_v1"
    bm25_candidates: int = Field(default=50, ge=1)  # per BM25 query, before fusion
    grep_max_matches: int = Field(default=40, ge=1)  # identifiers matching more are too common
    rrf_k: int = Field(default=60, ge=1)  # reciprocal-rank-fusion constant
    expansion_seeds: int = Field(default=5, ge=0)  # top fused chunks to expand from
    expansion_per_seed: int = Field(default=4, ge=0)  # per relation (callee, caller, ...)
    expansion_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    followup_max_searches: int = Field(default=3, ge=1)
    # A follow-up round runs only while results are "thin":
    followup_min_tests: int = Field(default=1, ge=0)  # fewer test chunks than this in top_k
    max_templates: int = Field(default=3, ge=0)
    max_ticket_chars: int = Field(default=6000, ge=200)  # ticket text sent to the LLM
    rerank: RerankSettings = RerankSettings()


class ContextSettings(_Section):
    max_tokens: int = Field(default=12000, ge=1)
    # Token estimate without a tokenizer: ceil(chars / chars_per_token). 3.0 over-counts for
    # typical code and English, so the real count stays under the budget.
    chars_per_token: float = Field(default=3.0, gt=0)


class GenerateSettings(_Section):
    prompt_version: str = "generate_v4"
    # Team conventions for tests (Markdown). Always placed in the context when set.
    conventions_doc: Path | None = None
    # Always on the reviewer checklist: things only a real run can confirm.
    review_checklist_defaults: list[str] = Field(
        default_factory=lambda: [
            "Expected backend responses are not from a real capture; confirm them in a real run.",
            "Check whether the page needs a refresh before a field is read again after saving.",
            "Confirm the save flow (object save, top-bar save and publish, or reset).",
        ]
    )
    # Class methods copied with the scaffold (setup/teardown with the class's options).
    scaffold_methods: list[str] = Field(
        default_factory=lambda: ["setup", "teardown", "setup_method", "teardown_method"]
    )
    placeholder_token: str = "{test_id:24}"  # unique names in data; N = max length
    max_example_tests: int = Field(default=4, ge=0)  # similar tests shown as style examples
    # Suite-specific decorator names for deployment-type skips (cloud-only / on-prem-only).
    deployment_decorators: dict[str, str] = Field(
        default_factory=lambda: {"cloud": "cloud_only", "on_prem": "on_prem_only"}
    )


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
    # Versioned prompt templates. Default: the repo's prompts/ directory.
    prompts_dir: Path | None = None


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
    index: IndexSettings = IndexSettings()
    data: DataSettings = DataSettings()
    style: StyleSettings = StyleSettings()
    draft: DraftSettings = DraftSettings()
    markers: MarkerSettings = MarkerSettings()
    eval: EvalSettings = EvalSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    context: ContextSettings = ContextSettings()
    generate: GenerateSettings = GenerateSettings()
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
