"""LLMClient backed by the Anthropic API (``anthropic`` SDK).

Credentials are resolved by the SDK (``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN``, or an
``ant auth login`` profile). Current Claude models reject non-default ``temperature`` and do
not accept a seed, so neither is sent; determinism is best-effort.
"""

from __future__ import annotations

from typing import Any

import anthropic

from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse

_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeAPIClient(LLMClient):
    def __init__(
        self,
        model: str,
        max_output_tokens: int = 16000,
        timeout_seconds: float = 300.0,
        fallbacks: bool = True,
        effort: str | None = None,
        client: Any = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_output_tokens
        self._fallbacks = fallbacks
        self._effort = effort
        self._client: Any = client or anthropic.Anthropic(timeout=timeout_seconds)

    def complete(self, request: LLMRequest) -> LLMResponse:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        messages = [
            {"role": m.role, "content": m.content} for m in request.messages if m.role != "system"
        ]
        output_config: dict[str, Any] = {}
        if request.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.json_schema}
        if self._effort:
            output_config["effort"] = self._effort

        kwargs: dict[str, Any] = {
            "model": request.model or self._model,
            "max_tokens": request.max_output_tokens or self._max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if output_config:
            kwargs["output_config"] = output_config

        try:
            if self._fallbacks:
                response = self._client.beta.messages.create(
                    betas=[_FALLBACK_BETA], fallbacks="default", **kwargs
                )
            else:
                response = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic API rejected the credentials (ANTHROPIC_API_KEY)") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Anthropic API rate limit reached; retry later") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not reach the Anthropic API: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMError("The model declined the request (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise LLMError("The response hit max_tokens and is incomplete")

        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        usage = response.usage
        return LLMResponse(
            text=text,
            model=str(response.model),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
