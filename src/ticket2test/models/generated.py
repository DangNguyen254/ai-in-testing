"""Generated tests: what the LLM returns (wire model) and the stored code + data pair."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

# Validation context keys (set by the generator).
CTX_TEST_PREFIX = "test_function_prefix"
CTX_CLASS_PREFIX = "test_class_prefix"


class EntryParts(BaseModel):
    """The unique parts of one JSON data entry, as JSON text (the schema can't describe
    free-form objects, so they arrive as strings and are parsed here)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    test_id: str
    seed_json: str
    inputs_json: str
    expected_json: str

    def parts(self) -> dict[str, dict[str, Any]]:
        return {
            "seed": _object(self.seed_json, "seed_json"),
            "inputs": _object(self.inputs_json, "inputs_json"),
            "expected": _object(self.expected_json, "expected_json"),
        }


def _object(text: str, field: str) -> dict[str, Any]:
    try:
        value = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    return value


class GenerationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    entries: list[EntryParts]
    notes: str

    @model_validator(mode="after")
    def _consistent(self, info: ValidationInfo) -> GenerationResponse:
        """The code must parse, define a test, and its pytest ids must equal the entry keys."""
        from ticket2test.generate.inspect import computed_test_ids  # avoid an import cycle

        context: Any = info.context if isinstance(info.context, dict) else {}
        ids = computed_test_ids(
            self.code,
            context.get(CTX_TEST_PREFIX, "test"),
            context.get(CTX_CLASS_PREFIX, "Test"),
        )
        keys = [e.test_id for e in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("entries contain duplicate test_id values")
        missing = [i for i in ids if i not in keys]
        extra = [k for k in keys if k not in ids]
        if missing or extra:
            raise ValueError(
                "entry test_ids must equal the pytest ids of the generated tests. "
                f"Computed from the code: {ids}. Missing entries: {missing}. "
                f"Entries for ids the code doesn't produce: {extra}."
            )
        for entry in self.entries:
            entry.parts()  # raises on invalid JSON parts
        return self


class TemplateEntryRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    entry_key: str


class GeneratedTest(BaseModel):
    """A generated test: a code file plus its JSON data entries, with traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    file_name: str  # where it would go in the target repo (repo-relative); never written there
    data_file_name: str
    data_entries: dict[str, dict[str, Any]]  # pytest id -> entry
    test_ids: list[str]
    template_entry_ref: TemplateEntryRef | None
    ticket_id: str
    draft_ref: str
    retrieved_chunk_ids: list[str]  # chunks actually placed in the context
    prompt_version: str
    provider: str
    model: str
    attempts: int = Field(ge=1)
    context_tokens: int = Field(ge=0)  # estimated
    redactions: int = Field(default=0, ge=0)
    notes: str = ""
    validation_report: dict[str, Any] | None = None  # Phase 7
    collect_report: dict[str, Any] | None = None  # Phase 7
