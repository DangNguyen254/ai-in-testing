"""Opt-in logging of full prompts and responses (``--debug-log`` only).

Prompts and responses may contain source code, so this is off by default and writes only to
the git-ignored ``paths.debug_log_dir``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ticket2test.llm.base import LLMClient, LLMRequest, LLMResponse


class DebugLoggingClient(LLMClient):
    def __init__(self, inner: LLMClient, log_dir: Path) -> None:
        self._inner = inner
        self._log_dir = log_dir

    def complete(self, request: LLMRequest) -> LLMResponse:
        response = self._inner.complete(request)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        record = {
            "time": now.isoformat(),
            "request": request.model_dump(mode="json"),
            "response": response.model_dump(mode="json"),
        }
        path = self._log_dir / f"llm-{now:%Y%m%d}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return response
