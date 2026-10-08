"""An LLMClient wrapper that masks prompt-injection payloads in every request.

Every message is masked (see ``security/masking.py``); when a request contains tokens, the
legend (prompt ``masking_legend_v1``) is added as a final user message. Responses come back
with tokens; the caller restores them in the structured result with ``masker_of(client)``.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from ticket2test.llm.base import LLMClient, LLMRequest, LLMResponse, Message
from ticket2test.prompts import PromptTemplate
from ticket2test.security.masking import TOKEN, Masker


class MaskingClient(LLMClient):
    def __init__(self, inner: LLMClient, masker: Masker, legend: PromptTemplate) -> None:
        self._inner = inner
        self.masker = masker
        self._legend = legend

    @property
    def inner(self) -> LLMClient:
        return self._inner

    def complete(self, request: LLMRequest) -> LLMResponse:
        messages = [
            Message(role=m.role, content=self.masker.mask(m.content)) for m in request.messages
        ]
        text = "\n".join(m.content for m in messages)
        if TOKEN.search(text):
            legend = self._legend.render_user(legend=self.masker.legend(text))
            messages.append(Message(role="user", content=f"{self._legend.system}\n\n{legend}"))
        return self._inner.complete(request.model_copy(update={"messages": tuple(messages)}))


def masker_of(client: LLMClient) -> Masker | None:
    """The masker of a masking client, also under other wrappers (None when masking is off)."""
    seen: LLMClient | None = client
    for _ in range(10):  # wrappers expose .inner; a short, bounded walk
        if isinstance(seen, MaskingClient):
            return seen.masker
        seen = getattr(seen, "inner", None)
        if seen is None:
            return None
    return None


M = TypeVar("M", bound=BaseModel)


def unmask_model(value: M, masker: Masker | None, context: dict[str, Any] | None = None) -> M:
    """Restore payloads in every string of a structured result (plain text fields)."""
    if masker is None:
        return value
    text = value.model_dump_json()
    restored = masker.unmask_json_text(text)
    if restored == text:
        return value
    return type(value).model_validate_json(restored, context=context)
