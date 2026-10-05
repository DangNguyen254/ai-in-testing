"""Provider-agnostic LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

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


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMClient(ABC):
    """Every LLM call in the pipeline goes through this interface."""

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send one request and return the raw text response."""
