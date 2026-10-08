"""Read a real test run's console output (pytest ``-v``, often with ``-s``) into results.

The real suite runs tests through its own wrapper script, on remote browsers; ticket2test never
runs them (the sandbox has no network). A human or CI runs the generated test with that script
and hands the console log to ``ticket2test results``. Everything here is parsing, no LLM.

What the parser relies on (pytest's own output, not the wrapper's):

- **sections**: ``==== <title> ====`` lines. Results are read from the run section ("test
  session starts"), failure details from "FAILURES" / "ERRORS", one-line reasons from "short
  test summary info". Other sections (the warnings summary repeats node ids) are ignored;
- **verbose results**: a node id (``path.py::Class::test[params]``), then the status word
  (PASSED, FAILED, ERROR, SKIPPED, XFAIL, XPASS): at the end of the node-id line, or, when
  ``-s`` lets the test print, on a later line of its own. xdist prints
  ``[gw0] [ 50%] PASSED <node id>``;
- **failure blocks**: ``____ <title> ____`` then the traceback; ``E   `` lines carry the error;
- **links**: lines matching ``results.link_pattern`` (e.g. a remote-browser session link) belong
  to the failure block they are in, else to the test that was running.

A node id's class part may be a decorator-generated variant (``TestX_chrome_..._r1``), so one
generated test can have several results, one per variant.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import ResultsSettings

Status = Literal["passed", "failed", "error", "skipped", "xfailed", "xpassed"]
Verdict = Literal["passed", "test_problem", "check_failed", "error", "not_run", "unclear"]

_STATUS = {
    "PASSED": "passed",
    "FAILED": "failed",
    "ERROR": "error",
    "SKIPPED": "skipped",
    "XFAIL": "xfailed",
    "XPASS": "xpassed",
}
_WORDS = "|".join(_STATUS)
_SECTION = re.compile(r"^={3,}\s*(.*?)\s*={3,}\s*$")
_BLOCK = re.compile(r"^_{3,}\s*(.*?)\s*_{3,}\s*$")
_NODE = re.compile(r"(?P<node>[\w./\\-]+\.py::[^\s]+)")
_AT_END = re.compile(rf"\s(?P<status>{_WORDS})(?:\s+\[\s*\d+%\])?\s*$")
_ALONE = re.compile(rf"^\s*(?P<status>{_WORDS})(?:\s+\[\s*\d+%\])?\s*$")
_XDIST = re.compile(rf"^\[gw\d+\]\s+(?:\[\s*\d+%\]\s+)?(?P<status>{_WORDS})\s+(?P<node>\S+)")
_SUMMARY = re.compile(rf"^(?P<status>{_WORDS})\s+(?P<node>\S+?)(?:\s+-\s+(?P<reason>.*))?$")
_ERROR_TYPE = re.compile(
    r"^E\s+(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Exit|Failure|Timeout))\b"
)


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str  # as printed: path::Class::test[params]
    file: str
    class_name: str | None
    test_id: str  # function name with params, as in the data files
    status: Status
    error_type: str | None = None
    message: str = ""  # the error lines (E ...) or the summary reason, shortened
    links: list[str] = Field(default_factory=list)


class RunLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[RunResult] = Field(default_factory=list)
    summary: str = ""  # pytest's final line, e.g. "1 passed, 1659 deselected in 413.07s"


def parse_console(text: str, settings: ResultsSettings) -> RunLog:
    link = re.compile(settings.link_pattern) if settings.link_pattern else None
    results: dict[str, RunResult] = {}
    log = RunLog()
    section = ""
    running: str | None = None  # node id whose status hasn't been printed yet
    last: str | None = None  # the latest test seen in the run section (for links)
    block: str | None = None  # failure block title
    block_lines: list[str] = []
    blocks: dict[str, list[str]] = {}
    links: dict[str, list[str]] = {}  # node id -> links, attached once results are known

    def record(node: str, status: str) -> None:
        results[node] = _result(node, _STATUS[status], results.get(node))

    for raw in text.splitlines():
        line = raw.rstrip()
        header = _SECTION.match(line)
        if header:
            if block is not None:
                blocks[block] = block_lines
                block, block_lines = None, []
            title = header.group(1)
            if re.search(r"\b\d+ (?:passed|failed|errors?|skipped|deselected)\b", title):
                log.summary = title
            section = title.lower()
            continue
        if "session starts" in section:
            xdist = _XDIST.match(line)
            if xdist:
                record(xdist.group("node"), xdist.group("status"))
                last = xdist.group("node")
                continue
            seen = _NODE.search(line)
            if seen and line.lstrip().startswith(seen.group("node")):
                running = last = seen.group("node")
                end = _AT_END.search(line)
                if end:
                    record(running, end.group("status"))
                    running = None
            elif running and (alone := _ALONE.match(line)):
                record(running, alone.group("status"))
                running = None
            if link and last:
                links.setdefault(last, []).extend(link.findall(line))
        elif section in ("failures", "errors"):
            title = _BLOCK.match(line)
            if title:
                if block is not None:
                    blocks[block] = block_lines
                block, block_lines = title.group(1), []
            elif block is not None:
                block_lines.append(line)
        elif "short test summary" in section:
            summary = _SUMMARY.match(line.strip())
            if summary:
                node = summary.group("node")
                record(node, summary.group("status"))
                if summary.group("reason") and not results[node].message:
                    results[node].message = _short(summary.group("reason"), settings)
    if block is not None:
        blocks[block] = block_lines

    for title, lines in blocks.items():
        node = _node_for_block(title, results)
        if node is None:
            continue
        result = results[node]
        errors = [ln for ln in lines if ln.startswith("E ")]
        if errors:
            result.message = _short("\n".join(e[1:].strip() for e in errors), settings)
            typed = next((m for e in errors if (m := _ERROR_TYPE.match(e))), None)
            result.error_type = typed.group("type") if typed else result.error_type
        if link:
            links.setdefault(node, []).extend(u for ln in lines for u in link.findall(ln))
    for node, found in links.items():
        if node in results:
            results[node].links = list(dict.fromkeys(found))
    for result in results.values():
        if result.error_type is None and result.message:
            head = re.match(
                r"([A-Za-z_][\w.]*(?:Error|Exception|Exit|Failure|Timeout))\b", result.message
            )
            result.error_type = head.group(1) if head else None
    log.results = list(results.values())
    return log


def verdict(results: list[RunResult], settings: ResultsSettings) -> Verdict:
    """One verdict over a test's results (all its variants and cases).

    passed: every result passed. test_problem: an error type that means the test itself is
    wrong (``results.test_problem_errors``: a name that doesn't exist, a missing data key, an
    element not found). check_failed: an assertion failed; either the test caught the bug or
    its expectation is wrong; the reviewer decides (the link shows the run). error: an error in
    setup or teardown. unclear: anything else.
    """
    if not results:
        return "not_run"
    bad = [r for r in results if r.status not in ("passed", "skipped", "xfailed")]
    if not bad:
        return "passed" if any(r.status == "passed" for r in results) else "not_run"
    types = {(r.error_type or "").rsplit(".", 1)[-1] for r in bad}
    if types & set(settings.test_problem_errors):
        return "test_problem"
    if all(r.status == "failed" and "AssertionError" in types for r in bad):
        return "check_failed"
    if any(r.status == "error" for r in bad):
        return "error"
    return "unclear"


def _result(node: str, status: str, old: RunResult | None) -> RunResult:
    file, _, rest = node.partition("::")
    parts = rest.split("::")
    if old is not None:
        old.status = status  # type: ignore[assignment]
        return old
    return RunResult(
        node_id=node,
        file=file.replace("\\", "/"),
        class_name=parts[0] if len(parts) > 1 else None,
        test_id=parts[-1],
        status=status,  # type: ignore[arg-type]
    )


def _node_for_block(title: str, results: dict[str, RunResult]) -> str | None:
    """A failure block title is ``Class.test[params]`` or ``test[params]``, after
    ``ERROR at setup of`` / ``ERROR at teardown of`` for errors."""
    title = re.sub(r"^ERROR at \w+ of\s+", "", title)
    cls, _, test = title.rpartition(".")
    if "[" in cls:  # a dot inside the params: no class part
        cls, test = "", title
    matches = [
        node
        for node, r in results.items()
        if r.test_id == test and (not cls or r.class_name == cls)
        and r.status in ("failed", "error")
    ]  # fmt: skip
    return matches[0] if len(matches) == 1 else None


def _short(text: str, settings: ResultsSettings) -> str:
    text = text.strip()
    limit = settings.max_message_chars
    return text if len(text) <= limit else text[: limit - 3] + "..."
