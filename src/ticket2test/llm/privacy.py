"""An LLMClient wrapper that redacts private terms from every request (see
``security/private.py``). It is the outermost wrapper, so nothing inside it (masking, debug
logs, the provider) sees the terms."""

from __future__ import annotations

from ticket2test.llm.base import LLMClient, LLMRequest, LLMResponse, Message
from ticket2test.security.private import PrivateTerms


class PrivacyClient(LLMClient):
    def __init__(self, inner: LLMClient, terms: PrivateTerms) -> None:
        self._inner = inner
        self._terms = terms
        self.redactions = 0  # matches redacted so far (a count, never the text)

    @property
    def inner(self) -> LLMClient:
        return self._inner

    def complete(self, request: LLMRequest) -> LLMResponse:
        messages = []
        for message in request.messages:
            text, count = self._terms.redact(message.content)
            self.redactions += count
            messages.append(Message(role=message.role, content=text))
        return self._inner.complete(request.model_copy(update={"messages": tuple(messages)}))
