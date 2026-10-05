"""Build the configured LLMClient. Provider modules are imported lazily."""

from __future__ import annotations

from ticket2test.config import Settings
from ticket2test.llm.base import LLMClient
from ticket2test.llm.debug import DebugLoggingClient


def create_llm_client(settings: Settings, debug_log: bool = False) -> LLMClient:
    llm = settings.llm
    client: LLMClient
    if llm.provider == "claude_code_cli":
        from ticket2test.llm.claude_code_cli import ClaudeCodeCLIClient

        client = ClaudeCodeCLIClient(
            model=llm.claude_code_cli.model,
            executable=llm.claude_code_cli.executable,
            workdir=llm.claude_code_cli.workdir,
            timeout_seconds=llm.timeout_seconds,
        )
    elif llm.provider == "claude":
        from ticket2test.llm.claude_api import ClaudeAPIClient

        client = ClaudeAPIClient(
            model=llm.claude.model,
            max_output_tokens=llm.max_output_tokens,
            timeout_seconds=llm.timeout_seconds,
            fallbacks=llm.claude.fallbacks,
            effort=llm.claude.effort,
        )
    else:
        from ticket2test.llm.gemini import GeminiClient

        client = GeminiClient(
            model=llm.gemini.model,
            max_output_tokens=llm.max_output_tokens,
            timeout_seconds=llm.timeout_seconds,
        )

    if debug_log:
        client = DebugLoggingClient(client, settings.paths.debug_log_dir)
    return client


def model_name(settings: Settings) -> str:
    llm = settings.llm
    if llm.provider == "claude_code_cli":
        return llm.claude_code_cli.model
    if llm.provider == "claude":
        return llm.claude.model
    return llm.gemini.model
