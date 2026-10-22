"""Usage metering: adds up calls, tokens and the provider-reported cost of every response."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ticket2test.llm.base import LLMClient, LLMRequest, LLMResponse


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    unpriced_calls: int = 0  # responses without a cost: the total is then a lower bound

    def minus(self, earlier: Usage) -> Usage:
        return Usage(
            calls=self.calls - earlier.calls,
            input_tokens=self.input_tokens - earlier.input_tokens,
            output_tokens=self.output_tokens - earlier.output_tokens,
            cost_usd=round(self.cost_usd - earlier.cost_usd, 6),
            unpriced_calls=self.unpriced_calls - earlier.unpriced_calls,
        )


class UsageMeter(LLMClient):
    """Wraps a client and records what each response reports. Failed calls count as calls."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self._usage = Usage()

    @property
    def usage(self) -> Usage:
        return self._usage

    def complete(self, request: LLMRequest) -> LLMResponse:
        u = self._usage
        try:
            response = self.inner.complete(request)
        except Exception:
            self._usage = u.model_copy(
                update={"calls": u.calls + 1, "unpriced_calls": u.unpriced_calls + 1}
            )
            raise
        self._usage = Usage(
            calls=u.calls + 1,
            input_tokens=u.input_tokens + (response.input_tokens or 0),
            output_tokens=u.output_tokens + (response.output_tokens or 0),
            cost_usd=round(u.cost_usd + (response.cost_usd or 0.0), 6),
            unpriced_calls=u.unpriced_calls + (response.cost_usd is None),
        )
        return response


def usage_of(client: LLMClient | None) -> Usage | None:
    """The running total if the client is metered, else None."""
    return client.usage if isinstance(client, UsageMeter) else None
