"""Usage metering: calls, tokens and the provider-reported cost add up."""

from __future__ import annotations

import pytest

from ticket2test.llm import FakeLLMClient, LLMError, LLMRequest, LLMResponse, Message
from ticket2test.llm.meter import Usage, UsageMeter, usage_of


class PricedFake(FakeLLMClient):
    """A fake that reports tokens and a cost per call, like the Claude CLI does."""

    def __init__(self, replies: list[str], cost: float | None = 0.25) -> None:
        super().__init__(replies)
        self.cost = cost

    def complete(self, request: LLMRequest) -> LLMResponse:
        response = super().complete(request)
        return response.model_copy(
            update={"input_tokens": 100, "output_tokens": 10, "cost_usd": self.cost}
        )


def _req() -> LLMRequest:
    return LLMRequest(messages=(Message(role="user", content="hi"),))


def test_the_meter_adds_up_and_differences_give_per_step_usage() -> None:
    meter = UsageMeter(PricedFake(["a", "b", "c"]))
    meter.complete(_req())
    start = meter.usage
    meter.complete(_req())
    meter.complete(_req())
    assert meter.usage == Usage(calls=3, input_tokens=300, output_tokens=30, cost_usd=0.75)
    assert meter.usage.minus(start) == Usage(
        calls=2, input_tokens=200, output_tokens=20, cost_usd=0.5
    )


def test_unpriced_and_failed_calls_are_counted() -> None:
    meter = UsageMeter(PricedFake(["a"], cost=None))
    meter.complete(_req())
    with pytest.raises(LLMError):
        meter.complete(_req())  # the fake has run out
    assert meter.usage.calls == 2 and meter.usage.unpriced_calls == 2
    assert meter.usage.cost_usd == 0.0


def test_usage_of_only_reads_metered_clients() -> None:
    assert usage_of(FakeLLMClient([])) is None and usage_of(None) is None
    assert usage_of(UsageMeter(FakeLLMClient([]))) == Usage()
