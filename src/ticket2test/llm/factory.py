"""Build the configured LLMClient. Provider modules are imported lazily."""

from __future__ import annotations

from ticket2test.config import LLMStep, Settings
from ticket2test.llm.base import LLMClient
from ticket2test.llm.debug import DebugLoggingClient
from ticket2test.llm.masking import MaskingClient
from ticket2test.prompts import load_prompt
from ticket2test.security.masking import Masker


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
    return with_privacy(with_masking(client, settings), settings)


def with_privacy(client: LLMClient, settings: Settings) -> LLMClient:
    """Redact private terms from every request (outermost: nothing inside sees them)."""
    from ticket2test.llm.privacy import PrivacyClient
    from ticket2test.security.private import PrivateTerms

    terms = PrivateTerms(settings.security.private_terms)
    return PrivacyClient(client, terms) if terms else client


def with_masking(client: LLMClient, settings: Settings) -> LLMClient:
    """Wrap a client so prompt-injection payloads are masked (outermost: logs see masks)."""
    masking = settings.security.masking
    if not masking.enabled:
        return client
    masker = Masker.from_config(masking.patterns, masking.keys, masking.min_chars)
    legend = load_prompt(masking.legend_prompt, settings.paths.prompts_dir)
    return MaskingClient(client, masker, legend)


def model_name(settings: Settings, step: LLMStep | None = None) -> str:
    """The configured provider's model, or the model mapped to ``step`` in its ``step_models``."""
    llm = settings.llm
    section = (
        llm.claude_code_cli
        if llm.provider == "claude_code_cli"
        else llm.claude
        if llm.provider == "claude"
        else llm.gemini
    )
    if step is not None and step in section.step_models:
        return section.step_models[step]
    return section.model
