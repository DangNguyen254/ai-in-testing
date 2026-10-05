"""Structured LLM output: JSON validated by a Pydantic model, with capped retry-with-error."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse, Message

T = TypeVar("T", bound=BaseModel)

_MAX_ERROR_CHARS = 2000


class StructuredOutputError(LLMError):
    """The model did not produce valid output within the retry budget."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    value: T
    response: LLMResponse
    attempts: int


def complete_structured(
    client: LLMClient,
    request: LLMRequest,
    model: type[T],
    max_retries: int,
    context: dict[str, Any] | None = None,
) -> StructuredResult[T]:
    """Call the LLM and validate its JSON against ``model``.

    On a parse or validation failure, the bad output and the error are sent back and the
    call is retried, at most ``max_retries`` times. Then ``StructuredOutputError`` is raised.
    ``context`` is passed to Pydantic validators (e.g. allowed values from config).
    """
    messages = list(request.messages)
    last_error = ""
    attempts = 0
    for attempts in range(1, max_retries + 2):
        response = client.complete(request.model_copy(update={"messages": tuple(messages)}))
        try:
            value = model.model_validate_json(_strip_fences(response.text), context=context)
        except ValidationError as exc:
            last_error = _short(exc.json(include_url=False, include_input=False))
        except json.JSONDecodeError as exc:  # pragma: no cover - pydantic wraps these
            last_error = _short(str(exc))
        else:
            return StructuredResult(value=value, response=response, attempts=attempts)

        messages += [
            Message(role="assistant", content=response.text),
            Message(
                role="user",
                content=(
                    "Your previous reply was not valid. Fix it and reply with only the corrected "
                    f"JSON object.\nValidation errors:\n{last_error}"
                ),
            ),
        ]
    raise StructuredOutputError(
        f"LLM output failed validation after {attempts} attempt(s): {last_error}", attempts
    )


def _strip_fences(text: str) -> str:
    """Tolerate a ```json fenced reply from providers without schema enforcement."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1 and stripped.endswith("```"):
            return stripped[first_newline + 1 : -3].strip()
    return stripped


def _short(text: str) -> str:
    return text if len(text) <= _MAX_ERROR_CHARS else text[:_MAX_ERROR_CHARS] + " ..."
