"""Provider-agnostic LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMError(RuntimeError):
    """Raised when an LLM call fails in a way the caller should handle."""


class Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: tuple[Message, ...]
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    json_mode: bool = True
    # When set, providers constrain the output to this JSON schema (see llm/schema.py).
    json_schema: dict[str, Any] | None = None
    # Per-request model override (e.g. a smaller model for a simple step); None = the client's.
    model: str | None = None


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None  # provider-reported estimate, if any


class LLMClient(ABC):
    """Every LLM call in the pipeline goes through this interface."""

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send one request and return the raw text response."""
