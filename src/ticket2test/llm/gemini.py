"""LLMClient backed by the Gemini API (``google-genai`` SDK). Key from ``GEMINI_API_KEY``."""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import errors, types

from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse

KEY_ENV_VAR = "GEMINI_API_KEY"


class GeminiClient(LLMClient):
    def __init__(
        self,
        model: str,
        max_output_tokens: int = 16000,
        timeout_seconds: float = 300.0,
        client: Any = None,
    ) -> None:
        if not model:
            raise LLMError("Gemini model is not set. Set llm.gemini.model in config.yaml.")
        self._model = model
        self._max_tokens = max_output_tokens
        if client is None:
            api_key = os.environ.get(KEY_ENV_VAR)
            if not api_key:
                raise LLMError(f"Set {KEY_ENV_VAR} to use the Gemini provider.")
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
            )
        self._client: Any = client

    def complete(self, request: LLMRequest) -> LLMResponse:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
            if m.role != "system"
        ]
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=request.temperature,
            seed=request.seed,
            max_output_tokens=request.max_output_tokens or self._max_tokens,
            response_mime_type="application/json" if request.json_mode else None,
            response_json_schema=request.json_schema,
        )
        try:
            response = self._client.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except errors.APIError as exc:
            raise LLMError(f"Gemini API error {exc.code}: {exc.message}") from exc

        text = response.text
        if not text:
            raise LLMError("Gemini returned no text (blocked or empty response)")
        usage = response.usage_metadata
        return LLMResponse(
            text=text,
            model=self._model,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )
