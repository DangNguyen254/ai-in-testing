from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, Field

from ticket2test.llm import FakeLLMClient, LLMRequest, Message
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import StructuredOutputError, complete_structured
from ticket2test.models.draft import DraftResponse


class Inner(BaseModel):
    label: str = Field(min_length=1, max_length=10)


class Outer(BaseModel):
    score: float = Field(ge=0, le=1)
    items: list[Inner] = Field(min_length=1)
    note: str | None = None


def _request() -> LLMRequest:
    return LLMRequest(messages=(Message(role="user", content="go"),))


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found += _walk(value)
    elif isinstance(node, list):
        for value in node:
            found += _walk(value)
    return found


# --- strict_schema ---------------------------------------------------------------------------


def test_strict_schema_closes_objects_and_drops_constraints() -> None:
    schema = strict_schema(Outer)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    for key in ("minimum", "maximum", "minLength", "maxLength", "minItems", "title"):
        assert f'"{key}"' not in text
    objects = [n for n in _walk(schema) if n.get("type") == "object"]
    assert len(objects) == 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])


def test_draft_response_schema_is_provider_safe() -> None:
    schema = strict_schema(DraftResponse)
    assert set(schema["required"]) == {"status", "missing_info", "reason", "drafts"}
    item = schema["properties"]["drafts"]["items"]
    assert item["properties"]["test_kind"]["enum"] == ["ui", "api", "hybrid"]
    assert item["properties"]["markers"]["additionalProperties"] is False


# --- complete_structured ---------------------------------------------------------------------

GOOD = json.dumps({"score": 0.5, "items": [{"label": "a"}], "note": None})


def test_valid_first_try() -> None:
    fake = FakeLLMClient([GOOD])
    result = complete_structured(fake, _request(), Outer, max_retries=2)
    assert result.value.score == 0.5
    assert result.attempts == 1
    assert len(fake.requests) == 1


def test_fenced_json_is_accepted() -> None:
    fake = FakeLLMClient([f"```json\n{GOOD}\n```"])
    assert complete_structured(fake, _request(), Outer, max_retries=0).attempts == 1


def test_retry_sends_error_back_then_succeeds() -> None:
    bad = json.dumps({"score": 5, "items": []})  # violates le=1 and min_length=1
    fake = FakeLLMClient([bad, GOOD])
    result = complete_structured(fake, _request(), Outer, max_retries=2)
    assert result.attempts == 2
    retry = fake.requests[1].messages
    assert [m.role for m in retry] == ["user", "assistant", "user"]
    assert retry[1].content == bad
    assert "score" in retry[2].content and "items" in retry[2].content


@pytest.mark.parametrize("max_retries", [0, 1, 2])
def test_malformed_output_fails_cleanly_after_cap(max_retries: int) -> None:
    fake = FakeLLMClient(["not json at all"] * 10)
    with pytest.raises(StructuredOutputError) as info:
        complete_structured(fake, _request(), Outer, max_retries=max_retries)
    assert info.value.attempts == max_retries + 1
    assert len(fake.requests) == max_retries + 1  # never more calls than the cap allows
    assert "failed validation" in str(info.value)


def test_validation_context_reaches_validators() -> None:
    reply = json.dumps(
        {
            "status": "insufficient_info",
            "missing_info": ["expected_behavior"],
            "reason": "r",
            "drafts": [],
        }
    )
    fake = FakeLLMClient([reply])
    result = complete_structured(
        fake, _request(), DraftResponse, max_retries=0, context={"priorities": ["P1"]}
    )
    assert result.value.status == "insufficient_info"
