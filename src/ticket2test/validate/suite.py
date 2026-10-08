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
from ticket2test.generate.generator import first_party
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.generated import GeneratedTest
from ticket2test.sandbox.runner import collect_suite
from ticket2test.validate.validator import module_imports, validate_generated

# Which config keys to look at when a check fails on hand-written tests.
CONFIG_HINTS: dict[str, str] = {
    "syntax": "index.ignore (exclude files that aren't Python 3)",
    "imports": "validation.external_modules (libraries the suite imports)",
    "names": "validation.base_classes, index.chain_roots (members must resolve through them)",
    "base_class": "validation.base_classes (every root base test classes inherit)",
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

    for path in _test_files(index, settings):
        code = (repo / path).read_text(encoding="utf-8")
        entries, layout, data_text = read_suite_data(repo, path, settings)
        ids = static_ids(index, path)
        generated = GeneratedTest(
            code=code,
            file_name=path,
            data_file_name=str(PurePosixPath(path).with_suffix(settings.index.data_file_suffix)),
            data_entries=entries,
            data_format=layout,
            test_ids=ids,
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
        result = validate_generated(
            generated,
            index.catalog,
            settings,
            roots,
            data_text=data_text,
            imports=imports,
            index=index,
        )
        report.test_files += 1
        report.tests += len(ids)
        file_errors = 0
        for finding in result.findings:
            if finding.severity == "warning":
                warnings[finding.check] += 1
            elif finding.check == "ids" and finding.message.startswith(_NOT_STATIC):
                report.not_static.append(path)  # suite tests may use computed parametrize
            else:
                errors[finding.check].append((path, finding.render()))
                file_errors += 1
        report.clean_files += int(file_errors == 0)

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


def compare_ids(repo: Path, index: IndexData, settings: Settings) -> IdComparison:
    """Static pytest ids (from the code) vs. ``pytest --collect-only`` in the sandbox."""
    static: set[str] = set()
    not_computed: list[str] = []
    for chunk in index.chunks:
        if chunk.kind != "test":
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


def read_suite_data(
    repo: Path, path: str, settings: Settings
) -> tuple[list[dict[str, Any]], Any, str | None]:
    """The test file's data entries as a list (object layout converted), the layout, the text."""
    data_path = repo / PurePosixPath(path).with_suffix(settings.index.data_file_suffix)
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
