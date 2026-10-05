from __future__ import annotations

import pytest

from ticket2test.llm import FakeLLMClient, LLMClient, LLMError, LLMRequest, Message


def _request(text: str = "hi") -> LLMRequest:
    return LLMRequest(messages=(Message(role="user", content=text),))


def test_fake_is_an_llm_client() -> None:
    assert isinstance(FakeLLMClient([]), LLMClient)


def test_returns_canned_responses_in_order_and_records_requests() -> None:
    fake = FakeLLMClient(['{"a": 1}', '{"b": 2}'])
    assert fake.complete(_request("one")).text == '{"a": 1}'
    assert fake.complete(_request("two")).text == '{"b": 2}'
    assert [r.messages[0].content for r in fake.requests] == ["one", "two"]
    assert fake.remaining == 0


def test_raises_when_exhausted() -> None:
    fake = FakeLLMClient(["only"])
    fake.complete(_request())
    with pytest.raises(LLMError, match="exhausted"):
        fake.complete(_request())


def test_request_defaults_are_deterministic() -> None:
    assert _request().temperature == 0.0
