"""Configuration: defaults < config.yaml < environment variables.

Environment variables use the ``T2T_`` prefix and ``__`` as the nesting delimiter,
e.g. ``T2T_RETRIEVAL__TOP_K=5`` overrides ``retrieval.top_k``.

Secrets (API keys, tokens) are never part of this config. Adapters and LLM clients
read them directly from the environment.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_PATH = Path("config.yaml")
CONFIG_PATH_ENV_VAR = "T2T_CONFIG"
_SECRET_NAME = re.compile(r"SECRET|TOKEN|PASSW|PWD|API_?KEY|PRIVATE_?KEY|CREDENTIAL|AUTH", re.I)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


# The pipeline's LLM steps; each provider may map some of them to another model.
LLMStep = Literal[
    "draft",
    "query_rewrite",
    "retrieval_followup",
    "investigate",
    "generate",
    "variant_plan",
    "guide",
    "propose",
]


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
    # Some suites join several values in one marker argument ("rules,profiles"); each part is
    # checked on its own. Empty: values are taken whole.
    value_separator: str = ","


class EvalSettings(_Section):
    # Ticket ids in skip reasons (used to mine ticket <-> test pairs from git history).
    ticket_id_pattern: str = r"\b[A-Z][A-Z0-9]+-\d+\b"
    max_commits: int = Field(default=5000, ge=1)  # git history mining: newest commits read


class DraftSettings(_Section):
    prompt_version: str = "draft_v2"
    # Comments go into the prompt in order until this many characters; the rest are dropped.
    max_comment_chars: int = Field(default=20000, ge=0)
    # A partial draft with open questions (draft/skeleton.py), one extra LLM call: "auto" when
    # the ticket is judged insufficient or lacks an explicit steps or expected section (checked
    # in code), "always" (every ticket, to compare), or "never".
    skeleton: Literal["auto", "always", "never"] = "auto"
    skeleton_prompt: str = "skeleton_v1"


class ClassVariantRule(_Section):
    """A class decorator that generates one test class per value (see index/inheritance.py)."""

    values_from: int = Field(default=0, ge=0)  # positional string arguments from here are values
    # Generated class name; placeholders: {cls}, {value}, {value_title} (title-cased, no "_").
    name: str = "{cls}{value_title}"


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
    # Repo-relative folders the suite puts on Python's import path (by its pytest config or a
    # conftest), e.g. the folder holding its framework package. A file's module name is its
    # path from the deepest such folder, the way tests import it. The repo root always counts.
    import_roots: list[str] = Field(default_factory=list)
    # Repo-relative folders where tests live. Empty: tests anywhere. Files outside them are
    # still indexed (framework code, page objects, helpers) but never count as tests.
    test_paths: list[str] = Field(default_factory=list)
    test_function_prefix: str = "test"
    test_class_prefix: str = "Test"
    data_file_suffix: str = ".json"  # test_x.py -> test_x.json
    # Also look for a data file per test function, named after it, next to the module
    # (test_x.py::test_y -> test_y.json); it wins over the module's file for that test.
    function_data_files: bool = True
    # A function's own data file holds its cases: the framework runs the test once per entry,
    # with the pytest id ``<function>[<entry id>]`` (entries name only the case).
    function_file_cases: bool = False
    # The suite's loader finds a function's data files by name prefix (``<function>*.json`` next
    # to the module) and runs every entry of all of them; the module's file is used only when
    # none matches.
    function_data_prefix: bool = False
    chain_roots: list[str] = Field(default_factory=lambda: ["nav"])
    max_chain_depth: int = Field(default=4, ge=1)
    # The chain list (for search, guides and context); page objects and validation don't
    # depend on it being complete. A truncated list is reported by `index`.
    max_chain_entries: int = Field(default=50000, ge=1)
    name_boost: int = Field(default=3, ge=1)  # symbol name repeats in the search text
    save_attempts: int = Field(default=5, ge=1)  # index file rename retries (Windows locks)
    # Class decorators that generate test-class variants (stand-in: ``variants(attr, *values)``).
    class_variant_decorators: dict[str, ClassVariantRule] = Field(
        default_factory=lambda: {"variants": ClassVariantRule(values_from=1)}
    )


def _default_sections() -> dict[str, str | list[str]]:
    return {"targets": "self.verify_targets", "interactions": "self.verify_interactions"}


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
    seed_sections: list[str] = Field(
        default_factory=lambda: ["settings", "policy", "tenants", "site"]
    )
    # Expectation section -> the validation helper that reads it. An entry has at most one,
    # and only when the test calls its helper.
    # A section may name several helpers, and names may be patterns (``*``): a suite where each
    # class has its own validation method (``self.*validate_result``), a module function
    # (``*.validate_api_response``), or a seeding call that checks its responses.
    expectation_sections: dict[str, str | list[str]] = Field(default_factory=_default_sections)
    # Per-entry overrides that a new entry never inherits from its base entry.
    per_entry_keys: list[str] = Field(default_factory=lambda: ["priority", "skip"])

    def section_helpers(self) -> dict[str, list[str]]:
        """Expectation section -> the helper names or patterns that read it."""
        return {
            section: [helpers] if isinstance(helpers, str) else list(helpers)
            for section, helpers in self.expectation_sections.items()
        }

    def helper_patterns(self) -> list[str]:
        """Every expectation helper name or pattern."""
        return [h for helpers in self.section_helpers().values() for h in helpers]

    # A first entry without the id field holds defaults for every entry in the file (array
    # layout); how the suite's loader combines them: top-level keys, or nested objects too.
    defaults_row: bool = True
    # shallow: an entry's top-level key replaces the default; shallow_if_set: only when the
    # entry's value is set (an empty or false value keeps the default); deep: nested objects too.
    defaults_merge: Literal["shallow", "shallow_if_set", "deep"] = "shallow"
    # Expectation sections an entry may carry together (each read by its own helper), e.g.
    # [[targets, interactions]]. Empty: at most one per entry.
    allowed_expectation_sets: list[list[str]] = Field(default_factory=list)


class PythonStyle(_Section):
    indent_width: int = Field(default=3, ge=1, le=8)
    line_length: int = Field(default=100, ge=40)
    line_ending: Literal["lf", "cr-lf"] = "lf"
    quote_style: Literal["double", "single"] = "double"
    strip_annotations: bool = True
    final_newline: bool = True
    # First-party import roots for import sorting; empty: the target repo's top-level packages.
    first_party: list[str] = Field(default_factory=list)
    # The suite's Python version ("3.8"): generated code is formatted for it and must parse
    # with that version's grammar (syntax only; newer library calls are not detected).
    # None: whatever this tool's Python accepts.
    target_version: str | None = Field(default=None, pattern=r"^3\.\d{1,2}$")


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
    # Cosmetic rules follow the local style: code added to an existing file takes that file's
    # indent and quotes (existing lines are never reformatted), and the suite's own files are
    # not judged against the settings above (check-suite lists them as deviations).
    follow_local: bool = True


class RerankSettings(_Section):
    """Deterministic, feature-based reranking of the fused candidates (no LLM)."""

    enabled: bool = True
    max_chunks_per_file: int = Field(default=3, ge=1)  # diversity in the final top_k
    min_tests: int = Field(default=2, ge=0)  # tests kept in top_k when any were found
    identifier_weight: float = Field(default=0.3, ge=0.0)  # references verified identifiers
    definition_weight: float = Field(default=0.2, ge=0.0)  # defines a verified identifier
    test_link_weight: float = Field(default=0.15, ge=0.0)  # a test of a top source chunk
    path_weight: float = Field(default=0.15, ge=0.0)  # ticket words in the file path


class InvestigatorSettings(_Section):
    """The retrieval investigator (retrieve/investigator.py): a bounded agent that explores the
    indexed suite with read-only tools. Replaces the follow-up rounds when enabled."""

    enabled: bool = False
    prompt: str = "investigator_v3"
    max_steps: int = Field(default=6, ge=1, le=20)  # LLM turns
    max_actions_per_step: int = Field(default=4, ge=1, le=6)
    max_tool_output_chars: int = Field(default=3000, ge=200)  # per tool call
    max_transcript_chars: int = Field(default=24000, ge=1000)  # older tool output is cut
    max_kept: int = Field(default=12, ge=1)
    results_per_search: int = Field(default=8, ge=1)


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
    # Action words for test shapes (retrieve/shape.py): templates of the draft's shape rank first
    # after the component. Name -> words found in test names, called names, or the draft.
    shape_actions: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "add": ["add", "create", "new"],
            "edit": ["edit", "update", "change", "rename", "modify", "enable", "disable", "toggle"],
            "delete": ["delete", "remove"],
        }
    )
    max_ticket_chars: int = Field(default=6000, ge=200)  # ticket text sent to the LLM
    rerank: RerankSettings = RerankSettings()
    investigator: InvestigatorSettings = InvestigatorSettings()


class ContextSettings(_Section):
    max_tokens: int = Field(default=12000, ge=1)
    # Token estimate without a tokenizer: ceil(chars / chars_per_token). 3.0 over-counts for
    # typical code and English, so the real count stays under the budget.
    chars_per_token: float = Field(default=3.0, gt=0)


class ReuseSettings(_Section):
    """How a draft is matched against existing tests (see generate/reuse.py)."""

    candidates: int = Field(default=8, ge=1)  # domain tests compared with the draft
    covered_min: float = Field(default=0.8, ge=0.0, le=1.0)  # flow match for "already covered"
    variant_min: float = Field(default=0.6, ge=0.0, le=1.0)  # flow match for "new variant"
    method_min: float = Field(default=0.4, ge=0.0, le=1.0)  # class match for "new method"
    # ... or this much when the class is named after the draft's subject (generate/reuse.py)
    method_named_min: float = Field(default=0.25, ge=0.0, le=1.0)
    domain_margin: float = Field(default=0.15, ge=0.0, le=1.0)  # closer than this: uncertain
    # Classes (or bases) new tests never go into: legacy or frozen code the team keeps as is.
    frozen_classes: list[str] = Field(default_factory=list)
    # Class decorators that list the deployments a class runs on (``environments("cloud")``).
    environment_decorators: list[str] = Field(default_factory=lambda: ["environments"])
    # Legacy areas (domain names or repo-relative folder globs): only "already covered" is
    # decided there; no test is generated or patched ("out_of_scope").
    legacy_domains: list[str] = Field(default_factory=lambda: ["units"])  # the stand-in's
    # UI tests in an area go only into classes that already use page objects (a chain root or
    # a path-string helper in some test), never into classes that drive the browser directly.
    ui_needs_page_objects: bool = True


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
    # Class methods copied with the scaffold (setup/teardown with the class's options). Real
    # suites mix pytest (setup_method, setup_class), nose-style (setup) and unittest (setUp).
    scaffold_methods: list[str] = Field(
        default_factory=lambda: [
            "setup", "teardown", "setup_method", "teardown_method", "setup_class",
            "teardown_class", "setUp", "tearDown", "setUpClass", "tearDownClass",
        ]
    )  # fmt: skip
    placeholder_token: str = "{test_id:24}"  # unique names in data; N = max length
    max_example_tests: int = Field(default=4, ge=0)  # similar tests shown as style examples
    # The decorator that limits a test to one deployment (cloud-only / on-prem-only): a name
    # (``cloud_only``) or a whole decorator expression, e.g. a skip on a condition
    # (``pytest.mark.skipif(OFFSET != 0, reason="cloud only")``); new tests get it as written.
    deployment_decorators: dict[str, str] = Field(
        default_factory=lambda: {"cloud": "cloud_only", "on_prem": "on_prem_only"}
    )
    # More ways the suite writes those gates (regexes over a decorator's text): deployment ->
    # patterns. A matching decorator limits the class to that deployment.
    deployment_gate_patterns: dict[str, list[str]] = Field(default_factory=dict)
    # Domains are folders: each folder matching one of these globs (repo-relative, "*" = one
    # folder level) is a domain, named after its last part. ``domains`` overrides with
    # explicit names -> folder globs (for domains spread over several folders).
    domain_globs: list[str] = Field(default_factory=lambda: ["tests/*"])
    domains: dict[str, list[str]] = Field(default_factory=dict)
    reuse: ReuseSettings = ReuseSettings()
    # New cases of an existing test: planned in code when the draft's inputs name the data
    # keys they change, else by one small LLM call with this prompt.
    variant_prompt: str = "variant_v1"


class NamingSettings(_Section):
    """Regexes for names in generated tests (full match)."""

    module: str = r"test_[a-z0-9_]+"
    test_class: str = r"Test[A-Z][A-Za-z0-9]*"
    test_function: str = r"test_[a-z0-9_]+"


class ValidateSettings(_Section):
    """Deterministic checks of a generated test (Phase 7). Values describe the target suite."""

    # Every test class must inherit one of these (directly or not); there may be no common root.
    # Empty: discovered from the suite (any in-repo class that existing test classes inherit;
    # real suites have dozens of bases, 2-4 levels deep, per area). ``discover_base_classes``
    # false and empty: the check is off.
    base_classes: list[str] = Field(default_factory=list)
    discover_base_classes: bool = True
    assertion_object: str = "self.check"
    # Other objects whose methods are assertions in existing tests (e.g. a module-level
    # ``check = unittest.TestCase()``). Generated tests use ``assertion_object``.
    extra_assertion_objects: list[str] = Field(default_factory=list)
    # Test classes with no base at all (``class TestX:``) pass the base-class check: some
    # suites keep plain API tests that way.
    baseless_classes: bool = False
    # Existing tests check by waiting: a wait call (name matching ``wait_patterns``) on a
    # condition, a raised failure (``AssertionError``, ``*Timeout*``, ``pytest.fail``), or a
    # page-object method that does either, counts as the test's check.
    wait_checks: bool = False
    wait_patterns: list[str] = Field(default_factory=lambda: ["*wait*", "*until*"])
    # Classes that inherit one of these (anywhere up the lineage) may also assert on ``self``
    # (``self.assertEqual``): real suites mix both styles. Only assert*/fail* methods count.
    testcase_bases: list[str] = Field(default_factory=lambda: ["unittest.TestCase", "TestCase"])
    # Tests never touch the page objects' locator constants (ALL_CAPS attributes): actions and
    # properties only. Off for suites whose tests use locators directly.
    forbid_page_locators: bool = True
    # Expressions that reach the raw browser driver; UI tests must not use them (page objects
    # only). Empty: the check is off.
    # Calls that count as a check besides the assertion object and the validation helpers:
    # name patterns of the suite's own checking helpers (``verify_*``, ``wait_for_log``).
    check_helpers: list[str] = Field(default_factory=list)
    # The suite uses relative imports (``from . import x``); off: a relative import is an error.
    relative_imports: bool = False
    # Expressions that reach the raw browser driver (``*`` is a wildcard, e.g.
    # ``self.driver.find_element*`` when ``self.driver`` itself is the framework's wrapper).
    raw_driver_access: list[str] = Field(default_factory=lambda: ["self.driver", "self._driver"])
    # Helpers that take a page-object path as a dotted string (``navigate("area.page")``) and
    # resolve it with getattr: the string is checked like a chain. Discovered too: functions
    # whose body splits a string on "." and calls getattr.
    path_string_helpers: list[str] = Field(default_factory=list)
    discover_path_string_helpers: bool = True
    assertion_methods: list[str] = Field(
        default_factory=lambda: [
            "assertEqual", "assertNotEqual", "assertTrue", "assertFalse", "assertIn",
            "assertNotIn", "assertIsNone", "assertIsNotNone", "assertGreater", "assertLess",
            "assertRaises",
        ]
    )  # fmt: skip
    # Importable besides the standard library and the target repo's own modules.
    external_modules: list[str] = Field(default_factory=lambda: ["pytest", "selenium"])
    naming: NamingSettings = NamingSettings()
    # Seeded object names: these keys in seed sections must use the unique-name placeholder.
    name_keys: list[str] = Field(default_factory=lambda: ["name"])
    # Seed sections whose objects need unique names (others, e.g. files on a fake site that
    # is reset for every test, may use fixed names).
    unique_name_sections: list[str] = Field(
        default_factory=lambda: ["settings", "policy", "tenants"]
    )
    name_max_length: int = Field(default=32, ge=1)  # the app's name length limit
    unique_name_helper: str = "self.unique_name"
    # Rules about how tests are written that existing tests may break (older code): on the
    # suite's own tests they are deviations, counted per area, not config errors. Generated
    # tests always follow them; when neighbouring tests don't, the reviewer gets a note.
    deviation_checks: list[str] = Field(
        default_factory=lambda: [
            "raw_driver",
            "page_locators",
            "constructed_pages",
            "star_imports",
        ]
    )
    # Suites whose base classes provide different unique-name helpers: base class name -> the
    # helper its tests call. A test uses the helper of the first base in its lineage listed
    # here (else ``unique_name_helper``); calling another base's helper is an error.
    unique_name_helpers: dict[str, str] = Field(default_factory=dict)
    # Data placeholders (regexes). Any placeholder makes a seeded name non-literal; the
    # unique-name one has the name's maximum length as its first group.
    placeholder_pattern: str = r"\{[a-z_]+\d*(?::\d+)?\}"
    unique_name_pattern: str = r"\{test_id:(\d+)\}"
    # Capability gates: where they sit in a seed section, and the gates each component's
    # features use. A component missing here is not checked.
    capability_path: str = "settings.capabilities"
    capability_gates: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "rules": ["rules", "bulk_delete", "import"],
            "profiles": ["profiles"],
            "settings": ["rules", "profiles", "bulk_delete", "import", "browser_limit"],
            "tenants": ["rules", "profiles"],
            "agent": ["browser_limit"],
        }
    )
    # Heuristic: a test that pages and checks counts should read the page size.
    paging_actions: list[str] = Field(default_factory=lambda: ["next_page", "previous_page"])
    constant_properties: list[str] = Field(default_factory=lambda: ["page_size"])


class RepairSettings(_Section):
    max_attempts: int = Field(default=3, ge=0)
    prompt_version: str = "repair_v1"


class SandboxSettings(_Section):
    runtime: Literal["docker", "podman"] = "docker"
    timeout_seconds: int = Field(default=120, ge=1)
    image: str = "t2t-sandbox:py3.12"  # built from sandbox/Containerfile (`ticket2test sandbox`)
    # What the image is built from: an approved base image with Python, and the target suite's
    # test-time requirements file (None: the packaged default, pytest + selenium pinned).
    base_image: str = "docker.io/library/python:3.12-slim"
    requirements: Path | None = None
    # False: the runtime gets an empty credentials file, so the sandbox never uses the
    # developer's registry logins (public base images pull anonymously). True: use them (for
    # a base image in a registry that needs a login).
    registry_auth: bool = False
    memory: str = "1g"
    pids_limit: int = Field(default=256, ge=16)
    # Staging folder for each run (inside the repo, git-ignored).
    work_dir: Path = Path(".scratch/sandbox")
    # What importing the target suite needs (set in the private config). `env`: non-secret
    # variables set in the container (names that look like secrets are refused). `stub_dir`: a
    # folder of stand-in modules, copied into the staging folder and put first on the import
    # path, for modules with import-time side effects. `extra_paths`: repo-relative folders
    # added to the import path. `collect_ignore`: repo-relative paths a whole-suite collect
    # skips (pytest --ignore); their tests are left out of the id comparison too.
    env: dict[str, str] = Field(default_factory=dict)
    stub_dir: Path | None = None
    extra_paths: list[str] = Field(default_factory=list)
    collect_ignore: list[str] = Field(default_factory=list)

    @field_validator("env")
    @classmethod
    def _no_secrets_in_env(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"sandbox.env: {name!r} is not a variable name")
            if _SECRET_NAME.search(name):
                raise ValueError(
                    f"sandbox.env: {name!r} looks like a secret; the sandbox gets no secrets "
                    "(stub the module that needs it instead)"
                )
        return value

    @field_validator("extra_paths", "collect_ignore")
    @classmethod
    def _repo_relative(cls, value: list[str]) -> list[str]:
        for path in value:
            parts = path.replace("\\", "/").split("/")
            if not re.fullmatch(r"[\w./-]+", path) or path.startswith("/") or ".." in parts:
                raise ValueError(f"{path!r} must be a plain repo-relative path")
        return value


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


class MaskingSettings(_Section):
    """Prompt-injection payloads are masked before any text reaches the LLM."""

    enabled: bool = True
    # Instruction-like phrasing (case-insensitive regexes): the enclosing string or sentence is
    # masked wherever it appears (tickets, data, code, validator messages).
    patterns: list[str] = Field(
        default_factory=lambda: [
            r"\bignore (?:all |any |previous |prior |the |above |earlier )*"
            r"(?:instructions|prompts?|rules)\b",
            r"\bdisregard (?:all |any |previous |prior |the |above )*(?:instructions|rules)\b",
            r"\byou (?:are|must) now\b",
            r"\bnew task:",
            r"\bsystem prompt\b",
            r"\bact as (?:an? )?(?:admin|administrator|developer|system)\b",
            r"</?\s*(?:system|assistant|tool_call|function_call)\b",
        ]
    )
    # JSON keys whose string values are always masked (where the suite keeps payloads).
    keys: list[str] = Field(default_factory=lambda: ["hidden_text", "comment", "alt", "meta"])
    min_chars: int = Field(default=1, ge=1)
    legend_prompt: str = "masking_legend_v1"


class ResultsSettings(_Section):
    """Reading a real run's console log (results/console.py)."""

    # Links in the log that belong to a test run (e.g. a remote-browser session).
    link_pattern: str = r"https?://(?:[\w-]+\.)*saucelabs\.com/\S+"
    # Error types that mean the test itself is wrong, not that it found the bug.
    test_problem_errors: list[str] = Field(
        default_factory=lambda: [
            "AttributeError",
            "NameError",
            "KeyError",
            "TypeError",
            "ImportError",
            "ModuleNotFoundError",
            "NoSuchElementException",
            "InvalidSelectorException",
        ]
    )
    # Error types that mean the run couldn't reach the system under test (not the test's
    # fault, not the bug): network, DNS, TLS, timeouts while connecting.
    environment_errors: list[str] = Field(
        default_factory=lambda: [
            "ConnectionError",
            "NewConnectionError",
            "MaxRetryError",
            "ConnectTimeout",
            "ConnectTimeoutError",
            "ReadTimeout",
            "SSLError",
            "gaierror",
            "ConnectionRefusedError",
            "ConnectionResetError",
        ]
    )
    max_message_chars: int = Field(default=1500, ge=100)


class SecuritySettings(_Section):
    masking: MaskingSettings = MaskingSettings()
    # Names that must never reach an external LLM or this repo (case-insensitive regexes; see
    # security/private.py). Set them in the private config or T2T_SECURITY__PRIVATE_TERMS
    # (a JSON list), never in this repo's config.yaml.
    private_terms: list[str] = Field(default_factory=list)


class MapSettings(_Section):
    """The suite map (suitemap/): area summaries built from the index by code."""

    max_items: int = Field(default=15, ge=1)  # per list in an area summary
    max_examples: int = Field(default=6, ge=1)  # typical tests per area, one per shape
    max_coverage_listed: int = Field(default=200, ge=0)  # in coverage.md; map.json has all
    # An area with more tests is split into one sub-area per module (<area>/<module>): real
    # suites have areas holding half of all tests, too much for one guide.
    max_tests_per_area: int = Field(default=300, ge=1)


class Price(_Section):
    input_per_mtok: float = Field(ge=0)  # USD per million input tokens
    output_per_mtok: float = Field(ge=0)


class GuideSettings(_Section):
    """Area guides (guides/): one LLM call per area, written once by a strong model (the
    ``guide`` step's model) and read by the generator on every ticket in that area."""

    prompt: str = "guide_v1"
    max_budget_usd: float = Field(default=50.0, ge=0)  # hard ceiling; --budget can't exceed it
    max_input_tokens: int = Field(default=20000, ge=1000)  # per area: summary + picked code
    max_piece_tokens: int = Field(default=3000, ge=200)  # a larger page object: outline only
    max_output_tokens: int = Field(default=4000, ge=500)  # asked for; not every provider obeys
    # Worst-case planning per call, raised by what real calls use (calibration.json next to the
    # guides). Defaults from the first run through the Claude CLI (2026-10-23): it adds up to
    # ~23k input tokens of its own; Opus wrote ~5.3k output tokens against a 4k cap.
    call_overhead_tokens: int = Field(default=25000, ge=0)
    output_allowance_tokens: int = Field(default=8000, ge=1)
    max_areas_per_run: int = Field(default=50, ge=1)
    dir: Path | None = None  # default: <output_dir>/guides/<repo folder name>
    use_in_generation: bool = True  # put the ticket's area guide into the generation context
    max_context_tokens: int = Field(default=1500, ge=200)  # of the guide, in that context
    # USD per million tokens, used for estimates and when the provider reports no cost.
    # Anthropic first-party API prices, as cached in the claude-api reference on 2026-10-06
    # (Haiku 5.5: prompts up to 100K tokens). Check your provider's price list.
    prices: dict[str, Price] = Field(
        default_factory=lambda: {
            "claude-opus-5-5": Price(input_per_mtok=4.0, output_per_mtok=20.0),
            "claude-sonnet-5-5": Price(input_per_mtok=2.0, output_per_mtok=10.0),
            "claude-haiku-5-5": Price(input_per_mtok=0.10, output_per_mtok=0.50),
        }
    )


class ProposalSettings(_Section):
    """Missing-piece proposals (agent 2, proposals/): for a reported gap on a test-side class,
    the LLM writes the one missing member; code checks that nothing existing changes. Opt-in."""

    enabled: bool = False
    prompt: str = "proposal_v1"
    max_per_ticket: int = Field(default=2, ge=1)  # gaps proposed for, per ticket
    max_repairs: int = Field(default=2, ge=0)  # rounds of check findings sent back
    collect: bool = True  # load the suite with the patch in the sandbox
    regenerate: bool = True  # generate the test again using the accepted members
    max_class_tokens: int = Field(default=3000, ge=200)  # larger classes go in as an outline


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
    results: ResultsSettings = ResultsSettings()
    context: ContextSettings = ContextSettings()
    generate: GenerateSettings = GenerateSettings()
    validation: ValidateSettings = ValidateSettings()
    repair: RepairSettings = RepairSettings()
    sandbox: SandboxSettings = SandboxSettings()
    security: SecuritySettings = SecuritySettings()
    map: MapSettings = MapSettings()
    guides: GuideSettings = GuideSettings()
    proposals: ProposalSettings = ProposalSettings()
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
