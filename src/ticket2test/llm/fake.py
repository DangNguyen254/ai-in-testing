"""Deterministic fake LLM client for tests."""

from __future__ import annotations

from collections.abc import Iterable

from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse


class FakeLLMClient(LLMClient):
    """Returns canned responses in order and records every request it receives.

    Raises ``LLMError`` once the canned responses run out, so a test can never
    loop forever against the fake.
    """

    def __init__(self, responses: Iterable[str], model: str = "fake-model") -> None:
        self._responses = list(responses)
        self._model = model
        self.requests: list[LLMRequest] = []

    @property
    def remaining(self) -> int:
        return len(self._responses)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise LLMError(f"FakeLLMClient exhausted after {len(self.requests) - 1} responses")
        return LLMResponse(text=self._responses.pop(0), model=self._model)
