"""Validation findings for a generated test.

``error`` findings block the test and go back to the LLM in the repair loop. ``warning``
findings never block: they are heuristics (claims vs. checks, unused gates, unstated
constants) shown to the reviewer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["error", "warning"]


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str  # short id of the validator, e.g. "names", "data_keys"
    severity: Severity
    message: str
    test: str | None = None  # test function or pytest id the finding is about
    line: int | None = None  # 1-based line in the generated code

    def render(self) -> str:
        where = " ".join(
            part for part in (self.test or "", f"line {self.line}" if self.line else "") if part
        )
        return f"[{self.check}] {where + ': ' if where else ''}{self.message}"


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)
    repairs: int = 0  # repair rounds run before this report
    history: list[list[str]] = Field(default_factory=list)  # errors sent in each round

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors
