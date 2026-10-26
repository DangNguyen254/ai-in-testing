"""Check a whole existing test suite against the config: calibration before generating.

The suite's own tests are known-good, so every validator error on them points at a config
value that doesn't describe the suite (marker values, style, data layout, base class, ...).
Each check's errors are grouped with the config keys most likely to fix them. Warnings
(heuristics) are only counted.

With ``collect``, the suite is also collected in the sandbox and the pytest ids are compared
with the ids computed statically from the code (the generator relies on those).
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ticket2test.config import Settings
from ticket2test.generate.domain import domain_of, domains, is_legacy
from ticket2test.generate.generator import first_party
from ticket2test.index.datafile import layout_of, split_defaults
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.generated import GeneratedTest
from ticket2test.sandbox.runner import ImportProblem, collect_suite
from ticket2test.validate.report import ValidationReport
from ticket2test.validate.validator import module_imports, validate_generated

# Which config keys to look at when a check fails on hand-written tests.
CONFIG_HINTS: dict[str, str] = {
    "syntax": "index.ignore (exclude files that aren't Python 3)",
    "imports": "validation.external_modules (libraries the suite imports)",
    "names": "validation.base_classes, index.chain_roots (members must resolve through them)",
    "base_class": "validation.base_classes (empty: discovered from existing test classes)",
    "hooks": "generate.scaffold_methods (the setup/teardown names the suite uses)",
    "page_locators": "validation.forbid_page_locators (off if tests use locators directly)",
    "raw_driver": "validation.raw_driver_access (the expressions that reach the raw driver)",
    "page_objects": "index.chain_roots; page objects may not use properties for values",
    "assertions": "validation.assertion_object, validation.assertion_methods",
    "markers": "markers.priorities, markers.suites, markers.project, markers.required",
    "naming": "validation.naming (module, test_class, test_function regexes)",
    "style": "style.python (indent_width, line_length, quote_style, strip_annotations, "
    "first_party)",
    "ids": "data.id_field, data.format, index.test_function_prefix / test_class_prefix",
    "data_keys": "data.access, data.seed_sections, data.expectation_sections, data.per_entry_keys",
    "data_file": "style.json (indent, separators, final_newline), data.format",
    "names_unique": "validation.name_keys, generate.placeholder_token",
    "name_length": "validation.name_max_length",
}
_NOT_STATIC = "parametrize values must be literals"
_EXAMPLES = 3


class Deviation(BaseModel):
    """Existing tests in one area that break a correctness rule, or don't follow the configured
    style (cosmetic: generated code follows the local style there)."""

    model_config = ConfigDict(extra="forbid")

    area: str
    check: str
    files: int
    tests: int
    examples: list[str] = Field(default_factory=list)


class CheckSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: str
    errors: int
    files: int
    hint: str
    examples: list[str] = Field(default_factory=list)


class IdComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ran: bool = False
    note: str = ""
    exit_code: int | None = None
    static: int = 0
    collected: int = 0
    only_static: list[str] = Field(default_factory=list)  # computed but not collected
    only_collected: list[str] = Field(default_factory=list)  # collected but not computed
    not_computed_tests: list[str] = Field(default_factory=list)  # ids need a real collect
    ignored_files: int = 0  # test files left out by sandbox.collect_ignore
    import_problems: list[ImportProblem] = Field(default_factory=list)  # modules that failed


class SuiteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    created_at: datetime
    test_files: int = 0
    tests: int = 0
    clean_files: int = 0
    errors: int = 0
    warnings: int = 0
    by_check: list[CheckSummary] = Field(default_factory=list)  # errors only
    warnings_by_check: dict[str, int] = Field(default_factory=dict)
    not_static: list[str] = Field(default_factory=list)  # files with non-literal parametrize
    legacy_files: int = 0  # test files in generate.reuse.legacy_domains (not checked)
    deviations: list[Deviation] = Field(default_factory=list)  # not config errors
    ids: IdComparison = Field(default_factory=IdComparison)
    seconds: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ok(self) -> bool:
        no_id_gaps = not (self.ids.only_static or self.ids.only_collected)
        return self.errors == 0 and (not self.ids.ran or (self.ids.exit_code == 0 and no_id_gaps))


def check_suite(repo: Path, settings: Settings, collect: bool = False) -> SuiteReport:
    started = time.monotonic()
    index, _, _ = update_index(repo, settings)
    report = SuiteReport(repo=str(repo), created_at=datetime.now(UTC))
    roots = first_party(index, settings)
    imports = module_imports(index)
    errors: dict[str, list[tuple[str, str]]] = defaultdict(list)  # check -> (file, message)
    warnings: dict[str, int] = defaultdict(int)

    all_domains = domains(index, settings)
    legacy = settings.generate.reuse.legacy_domains
    local = local_checks(settings)
    found: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for path in _test_files(index, settings):
        domain = domain_of(path, all_domains)
        if domain is not None and is_legacy(domain, legacy):
            report.legacy_files += 1
            continue
        result = file_findings(repo, path, index, settings, roots, imports)
        report.test_files += 1
        report.tests += len(static_ids(index, path))
        file_errors = 0
        for finding in result.findings:
            if finding.check in local and finding.severity == "error":
                area = domain.name if domain else "(no area)"
                found[(area, finding.check)].append((path, finding.test or "", finding.render()))
            elif finding.severity == "warning":
                warnings[finding.check] += 1
            elif finding.check == "ids" and finding.message.startswith(_NOT_STATIC):
                report.not_static.append(path)  # suite tests may use computed parametrize
            else:
                errors[finding.check].append((path, finding.render()))
                file_errors += 1
        report.clean_files += int(file_errors == 0)

    report.deviations = [
        Deviation(
            area=area,
            check=check,
            files=len({f for f, _, _ in rows}),
            tests=len({(f, t) for f, t, _ in rows if t}),
            examples=[f"{f}: {m}" for f, _, m in rows[:_EXAMPLES]],
        )
        for (area, check), rows in sorted(found.items(), key=lambda kv: (kv[0][0], -len(kv[1])))
    ]
    report.by_check = [
        CheckSummary(
            check=check,
            errors=len(found),
            files=len({f for f, _ in found}),
            hint=CONFIG_HINTS.get(check, ""),
            examples=[f"{f}: {m}" for f, m in found[:_EXAMPLES]],
        )
        for check, found in sorted(errors.items(), key=lambda kv: -len(kv[1]))
    ]
    report.errors = sum(s.errors for s in report.by_check)
    report.warnings_by_check = dict(sorted(warnings.items()))
    report.warnings = sum(warnings.values())
    if collect:
        report.ids = compare_ids(repo, index, settings)
    report.seconds = round(time.monotonic() - started, 1)
    return report


COSMETIC_CHECKS = ("style", "data_file")


def local_checks(settings: Settings) -> set[str]:
    """Checks whose errors on existing tests describe the suite, not the config: the
    correctness rules older tests may break, and (``style.follow_local``) the cosmetic ones."""
    cosmetic = set(COSMETIC_CHECKS) if settings.style.follow_local else set()
    return set(settings.validation.deviation_checks) | cosmetic


def file_findings(
    repo: Path,
    path: str,
    index: IndexData,
    settings: Settings,
    roots: list[str] | None = None,
    imports: dict[str, list[str]] | None = None,
) -> ValidationReport:
    """Every validator over one existing test file and its data, as if it were generated."""
    code = (repo / path).read_text(encoding="utf-8")
    entries, layout, data_text = read_suite_data(repo, path, settings)
    extra = _function_file_entries(repo, path, index, settings)
    if extra:  # tests with their own data file: judge them with their entries
        entries, data_text = [*entries, *extra], None  # formatting is per file: not here
    generated = GeneratedTest(
        code=code,
        file_name=path,
        data_file_name=str(PurePosixPath(path).with_suffix(settings.index.data_file_suffix)),
        data_entries=entries,
        data_format=layout,
        test_ids=static_ids(index, path),
        template_entry_ref=None,
        ticket_id="",
        draft_ref="",
        retrieved_chunk_ids=[],
        prompt_version="",
        provider="",
        model="",
        attempts=1,
        context_tokens=0,
    )
    return validate_generated(
        generated,
        index.catalog,
        settings,
        roots if roots is not None else first_party(index, settings),
        data_text=data_text,
        imports=imports if imports is not None else module_imports(index),
        index=index,
    )


def compare_ids(repo: Path, index: IndexData, settings: Settings) -> IdComparison:
    """Static pytest ids (from the code) vs. ``pytest --collect-only`` in the sandbox."""
    static: set[str] = set()
    not_computed: list[str] = []
    ignored = [p.strip("/") for p in settings.sandbox.collect_ignore]
    ignored_files: set[str] = set()
    for chunk in index.chunks:
        if chunk.kind != "test":
            continue
        if any(chunk.file_path == p or chunk.file_path.startswith(p + "/") for p in ignored):
            ignored_files.add(chunk.file_path)
            continue
        for class_name in chunk.collected_classes or [chunk.class_name or ""]:
            node = _node_prefix(chunk.file_path, class_name)
            if not chunk.test_ids_computed:
                not_computed.append(f"{node}{chunk.symbol_name}")
                continue
            static.update(f"{node}{test_id}" for test_id in chunk.test_ids)
    run = collect_suite(repo, settings)
    comparison = IdComparison(
        ran=True,
        exit_code=run.exit_code,
        static=len(static),
        collected=len(run.node_ids),
        not_computed_tests=sorted(not_computed),
        ignored_files=len(ignored_files),
        import_problems=run.import_problems,
    )
    if run.timed_out:
        comparison.note = "timed out (sandbox.timeout_seconds)"
        return comparison
    if run.exit_code not in (0, 5):  # 5: no tests collected
        comparison.note = run.output_tail[-1500:]
    skip = tuple(n + "::" for n in not_computed) + tuple(n + "[" for n in not_computed)
    collected = {n for n in run.node_ids if not n.startswith(skip) and n not in not_computed}
    comparison.only_static = sorted(static - collected)
    comparison.only_collected = sorted(collected - static)
    return comparison


def render_markdown(report: SuiteReport) -> str:
    lines = [
        f"# Suite check: {report.repo} ({report.created_at:%Y-%m-%d %H:%M UTC})",
        "",
        f"- Test files: {report.test_files} ({report.clean_files} without errors), "
        f"tests: {report.tests}",
        f"- **Errors: {report.errors}** (each points at a config value that doesn't match the "
        f"suite), warnings: {report.warnings} (heuristics, counted only)",
        f"- Result: **{'clean' if report.ok else 'config needs changes'}**",
        "",
    ]
    if report.by_check:
        lines += [
            "## Errors by check",
            "",
            "| Check | Errors | Files | Look at |",
            "|---|---|---|---|",
        ]
        lines += [f"| {s.check} | {s.errors} | {s.files} | {s.hint} |" for s in report.by_check]
        lines += ["", "Examples:"]
        for s in report.by_check:
            lines += [f"- {e}" for e in s.examples]
        lines.append("")
    if report.legacy_files:
        lines += [
            f"Legacy test files not checked (generate.reuse.legacy_domains): {report.legacy_files}",
            "",
        ]
    if report.deviations:
        lines += [
            "## Deviations (existing tests; not config errors)",
            "",
            "Correctness rules older tests break, and files not in the configured style. "
            "Generated tests follow the rules (with a reviewer note in these areas) and the "
            "local style.",
            "",
            "| Area | Check | Files | Tests |",
            "|---|---|---|---|",
        ]
        lines += [f"| {d.area} | {d.check} | {d.files} | {d.tests} |" for d in report.deviations]
        lines.append("")
    if report.warnings_by_check:
        counts = ", ".join(f"{k} {v}" for k, v in report.warnings_by_check.items())
        lines += ["## Warnings (counted only)", "", counts, ""]
    if report.not_static:
        lines += [
            "## Parametrize values not literal",
            "",
            "Ids for these files are known only after a real collect (fine for existing tests; "
            "generated tests must use literals):",
            "",
            *(f"- {f}" for f in sorted(set(report.not_static))),
            "",
        ]
    ids = report.ids
    lines += ["## Test ids: static vs. collected", ""]
    if not ids.ran:
        lines.append(
            "Not run (use `--collect`; needs the sandbox image with the suite's requirements)."
        )
    else:
        lines += [
            f"- pytest exit code: {ids.exit_code}; static ids: {ids.static}; collected: "
            f"{ids.collected}",
            f"- Computed but not collected: {len(ids.only_static)}; collected but not computed: "
            f"{len(ids.only_collected)}; tests whose ids need a real collect: "
            f"{len(ids.not_computed_tests)}",
        ]
        lines += [f"  - only static: `{n}`" for n in ids.only_static[:10]]
        lines += [f"  - only collected: `{n}`" for n in ids.only_collected[:10]]
        if ids.ignored_files:
            lines.append(f"- Test files left out (sandbox.collect_ignore): {ids.ignored_files}")
        if ids.import_problems:
            lines += ["", "Modules that failed to import (fix with sandbox settings or stubs):", ""]
            lines += [f"- `{p.path}`: {p.error}" for p in ids.import_problems[:30]]
            more = len(ids.import_problems) - 30
            lines += [f"- ... and {more} more"] if more > 0 else []
        if ids.note:
            lines += ["", "Collect output:", "", "```", ids.note, "```"]
    return "\n".join(lines) + "\n"


def _test_files(index: IndexData, settings: Settings) -> list[str]:
    """Files that match the test-file globs and actually contain tests."""
    globs = settings.index.test_file_globs
    with_tests = {c.file_path for c in index.chunks if c.kind == "test"}
    return sorted(
        path for path in with_tests if any(fnmatch(PurePosixPath(path).name, g) for g in globs)
    )


def static_ids(index: IndexData, path: str) -> list[str]:
    return [
        test_id
        for chunk in index.chunks
        if chunk.kind == "test" and chunk.file_path == path
        for test_id in chunk.test_ids
    ]


def _function_file_entries(
    repo: Path, path: str, index: IndexData, settings: Settings
) -> list[dict[str, Any]]:
    """Entries of the module's tests that keep their data in a file of their own."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in index.chunks:
        if chunk.kind != "test" or chunk.file_path != path or not chunk.data_file:
            continue
        if chunk.data_file in seen:
            continue
        own = layout_of(chunk.file_path, chunk.symbol_name, chunk.data_file, settings.index)
        if own != "function":
            continue
        seen.add(chunk.data_file)
        rows, _, _ = read_suite_data(repo, path, settings, chunk.data_file)
        found += split_defaults(rows, settings.data)[1]
    return found


def read_suite_data(
    repo: Path, path: str, settings: Settings, data_path_name: str | None = None
) -> tuple[list[dict[str, Any]], Any, str | None]:
    """The test file's data entries as a list (object layout converted; a defaults row kept as
    the first row), the layout, the text. ``data_path_name``: a data file other than the
    module's (a per-function file)."""
    name = data_path_name or str(PurePosixPath(path).with_suffix(settings.index.data_file_suffix))
    data_path = repo / name
    if not data_path.is_file():
        return [], settings.data.format, None
    text = data_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [], settings.data.format, text
    if isinstance(data, dict):
        entries = [
            {settings.data.id_field: key, **value}
            for key, value in data.items()
            if isinstance(value, dict)
        ]
        return entries, "object", text
    return [e for e in data if isinstance(e, dict)], "array", text


def _node_prefix(file_path: str, class_name: str) -> str:
    return f"{file_path}::{class_name}::" if class_name else f"{file_path}::"
